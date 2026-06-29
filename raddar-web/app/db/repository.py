"""Event read layer.

Two backends:
  * InMemoryRepository — seeded Dublin data, runs with zero credentials (dev/demo).
  * AirtableRepository — production read layer (stub; wire to the shared base).

Selection is driven by Settings.db_backend so the rest of the app is backend-agnostic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx
from loguru import logger
from pydantic import ValidationError

from app.config import Settings
from app.models import Category, CostTier, Event, SourceTier

# Airtable REST API base; per-record default duration when end_time is missing.
_AIRTABLE_API = "https://api.airtable.com/v0"
_DEFAULT_DURATION = timedelta(hours=2)


def _parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 string to a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class EventRepository(Protocol):
    async def list_active(self) -> list[Event]:
        """Return all non-expired events; temporal/geo filtering happens in the service layer."""
        ...

    async def get(self, event_id: str) -> Event | None:
        ...

    async def create(self, event: Event) -> None:
        """Persist a single event (used by user-hosted pins)."""
        ...

    async def count_active_by_user(self, user_id: str) -> int:
        """Number of the user's own non-expired hosted pins (for the per-user hosting quota)."""
        ...

    async def list_by_user(self, user_id: str) -> list[Event]:
        """The user's own non-expired hosted pins (for the 'your pins' view)."""
        ...

    async def update(self, event: Event) -> None:
        """Replace a stored event by id (used when a user edits their own pin)."""
        ...

    async def delete(self, event_id: str) -> None:
        """Remove a stored event by id (used when a user deletes their own pin)."""
        ...


# User-hosted events for the in-memory backend (the seed regenerates each call, so hosted
# pins need their own store to persist within the process).
_hosted_events: list[Event] = []


def _seed_events(anchor_lat: float, anchor_lng: float) -> list[Event]:
    """A handful of Dublin events spread across time and short distances from the anchor."""
    now = datetime.now(timezone.utc)

    def at(minutes_from_now: int, duration_min: int) -> tuple[datetime, datetime]:
        start = now + timedelta(minutes=minutes_from_now)
        return start, start + timedelta(minutes=duration_min)

    # small lat/lng offsets ≈ a few hundred metres around the anchor
    specs = [
        ("Trad session at The Cobblestone", Category.music, CostTier.free, 0, 150, 0.004, -0.012),
        ("Eatyard street food", Category.food, CostTier.low, 20, 180, -0.003, 0.006),
        ("Temple Bar Food Market", Category.market, CostTier.free, -30, 25, 0.001, 0.002),
        ("Gig at Whelan's", Category.nightlife, CostTier.mid, 150, 180, 0.006, -0.004),
        ("Pop-up gallery, Francis St", Category.art, CostTier.free, 60, 240, -0.006, -0.008),
        ("5-a-side, Phoenix Park edge", Category.sports, CostTier.free, 45, 90, 0.012, -0.02),
        ("Community swap, Liberties", Category.community, CostTier.free, 200, 120, -0.01, 0.004),
    ]

    events: list[Event] = []
    for i, (title, cat, cost, start_min, dur, dlat, dlng) in enumerate(specs):
        start, end = at(start_min, dur)
        events.append(
            Event(
                event_id=f"seed-{i:03d}",
                title=title,
                category=cat,
                start_time=start,
                end_time=end,
                lat=anchor_lat + dlat,
                lng=anchor_lng + dlng,
                cost_tier=cost,
                source_tier=SourceTier.editorial,
                source_name="seed",
                expires_at=end,
            )
        )
    return events


class InMemoryRepository:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def list_active(self) -> list[Event]:
        # regenerate seed each call so its times stay relative to "now" during dev,
        # then merge in any non-expired user-hosted pins
        now = datetime.now(timezone.utc)
        seeded = _seed_events(self._settings.anchor_lat, self._settings.anchor_lng)
        return [e for e in (seeded + _hosted_events) if (e.expires_at or e.end_time) > now]

    async def get(self, event_id: str) -> Event | None:
        for e in await self.list_active():
            if e.event_id == event_id:
                return e
        return None

    async def create(self, event: Event) -> None:
        _hosted_events.append(event)

    async def count_active_by_user(self, user_id: str) -> int:
        now = datetime.now(timezone.utc)
        return sum(
            1
            for e in _hosted_events
            if e.created_by == user_id and (e.expires_at or e.end_time) > now
        )

    async def list_by_user(self, user_id: str) -> list[Event]:
        now = datetime.now(timezone.utc)
        own = [
            e
            for e in _hosted_events
            if e.created_by == user_id and (e.expires_at or e.end_time) > now
        ]
        own.sort(key=lambda e: e.end_time)  # soonest-ending first, like discovery
        return own

    async def update(self, event: Event) -> None:
        for i, e in enumerate(_hosted_events):
            if e.event_id == event.event_id:
                _hosted_events[i] = event
                return

    async def delete(self, event_id: str) -> None:
        _hosted_events[:] = [e for e in _hosted_events if e.event_id != event_id]


class AirtableRepository:
    """Production read layer against the shared Airtable base.

    Hits the Airtable REST API with httpx, paginates, and validates every record into the
    canonical Event model before returning. Malformed records are rejected to the log
    (dead-letter), never silently corrupting the result set. Event status/times are not
    cached — they must always reflect the live store.

    A pre-built httpx.AsyncClient may be injected (used in tests via MockTransport).
    """

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        if not settings.airtable_api_key or not settings.airtable_base_id:
            raise RuntimeError("Airtable backend requires AIRTABLE_API_KEY and AIRTABLE_BASE_ID")
        self._settings = settings
        self._client = client

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{_AIRTABLE_API}/{self._settings.airtable_base_id}",
            headers={"Authorization": f"Bearer {self._settings.airtable_api_key}"},
            timeout=10.0,
        )

    async def _fetch_records(self) -> list[dict[str, Any]]:
        client = self._client or self._new_client()
        owns_client = self._client is None
        records: list[dict[str, Any]] = []
        params: dict[str, str] = {}
        try:
            while True:
                resp = await client.get(f"/{self._settings.airtable_table}", params=params)
                resp.raise_for_status()
                data = resp.json()
                records.extend(data.get("records", []))
                offset = data.get("offset")
                if not offset:
                    break
                params = {"offset": offset}
        finally:
            if owns_client:
                await client.aclose()
        return records

    @staticmethod
    def _parse(record: dict[str, Any]) -> Event:
        """Map one Airtable record → canonical Event. Raises on missing/invalid fields."""
        f = record.get("fields", {})
        start = _parse_dt(f["start_time"])
        end = _parse_dt(f["end_time"]) if f.get("end_time") else start + _DEFAULT_DURATION
        return Event(
            event_id=str(f.get("event_id") or record["id"]),
            title=f["title"],
            category=f["category"],
            start_time=start,
            end_time=end,
            lat=float(f["lat"]),
            lng=float(f["lng"]),
            cost_tier=f.get("cost_tier", CostTier.free.value),
            source_tier=f.get("source_tier", SourceTier.api.value),
            source_name=f.get("source_name", "airtable"),
            expires_at=_parse_dt(f["expires_at"]) if f.get("expires_at") else None,
        )

    async def list_active(self) -> list[Event]:
        now = datetime.now(timezone.utc)
        events: list[Event] = []
        for record in await self._fetch_records():
            try:
                event = self._parse(record)
            except (KeyError, ValueError, TypeError, ValidationError) as exc:
                logger.warning(
                    "airtable record rejected id={} err={}", record.get("id"), exc
                )
                continue
            if (event.expires_at or event.end_time) > now:
                events.append(event)
        return events

    async def get(self, event_id: str) -> Event | None:
        for event in await self.list_active():
            if event.event_id == event_id:
                return event
        return None

    async def create(self, event: Event) -> None:  # pragma: no cover - read-only source
        raise NotImplementedError("Airtable is a read-only events source")

    async def count_active_by_user(self, user_id: str) -> int:  # pragma: no cover - read-only
        return 0  # Airtable holds no user-hosted pins (create() is unsupported)

    async def list_by_user(self, user_id: str) -> list[Event]:  # pragma: no cover - read-only
        return []  # Airtable holds no user-hosted pins

    async def update(self, event: Event) -> None:  # pragma: no cover - read-only
        raise NotImplementedError("Airtable is a read-only events source")

    async def delete(self, event_id: str) -> None:  # pragma: no cover - read-only
        raise NotImplementedError("Airtable is a read-only events source")


def get_repository(settings: Settings) -> EventRepository:
    if settings.db_backend == "airtable":
        return AirtableRepository(settings)
    return InMemoryRepository(settings)
