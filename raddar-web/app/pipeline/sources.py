"""Event sources behind one interface.

`FixtureSource` reads raw records from a JSON file so the whole pipeline runs with no
credentials. `EventbriteSource` is a real client (auth, pagination, retry, online-event
filtering, venue→coords). `PredictHQSource` is a stub to fill in the same way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.pipeline.http import request_with_retry
from app.pipeline.schema import RawEvent


class EventSource(Protocol):
    name: str

    async def fetch(self) -> list[RawEvent]: ...


class FixtureSource:
    """Loads raw records from a JSON array file. Dev/test only."""

    def __init__(self, path: str | Path, *, name: str = "fixture") -> None:
        self.name = name
        self._path = Path(path)

    async def fetch(self) -> list[RawEvent]:
        data = json.loads(self._path.read_text())
        return [RawEvent.model_validate(item) for item in data]


# Eventbrite category_id → our normalizable category synonym. Unknowns default to community.
_EB_CATEGORY = {
    "103": "music",
    "110": "food",
    "105": "art",  # Performing & Visual Arts
    "108": "sports",
    "113": "community",
}


class EventbriteSource:
    """Eventbrite organization events. Drops online events (Now-and-Next = physical only)."""

    name = "eventbrite"
    _BASE = "https://www.eventbriteapi.com/v3"

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        if not settings.eventbrite_token or not settings.eventbrite_organization_id:
            raise RuntimeError("Eventbrite needs EVENTBRITE_TOKEN and EVENTBRITE_ORGANIZATION_ID")
        self._settings = settings
        self._client = client

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._BASE,
            headers={"Authorization": f"Bearer {self._settings.eventbrite_token}"},
            timeout=10.0,
        )

    async def fetch(self) -> list[RawEvent]:
        client = self._client or self._new_client()
        owns_client = self._client is None
        org = self._settings.eventbrite_organization_id
        path = f"/organizations/{org}/events/"
        params: dict[str, Any] = {"expand": "venue", "status": "live", "order_by": "start_asc"}
        raws: list[RawEvent] = []
        try:
            while True:
                resp = await request_with_retry(client, "GET", path, params=params)
                resp.raise_for_status()
                data = resp.json()
                for ev in data.get("events", []):
                    raw = self._to_raw(ev)
                    if raw is not None:
                        raws.append(raw)
                page = data.get("pagination", {})
                if not page.get("has_more_items") or not page.get("continuation"):
                    break
                params = {**params, "continuation": page["continuation"]}
        finally:
            if owns_client:
                await client.aclose()
        return raws

    @staticmethod
    def _to_raw(ev: dict[str, Any]) -> RawEvent | None:
        if ev.get("online_event"):
            return None  # physical events only
        venue = ev.get("venue") or {}
        lat = venue.get("latitude")
        lng = venue.get("longitude")
        address = (venue.get("address") or {}).get("localized_address_display")
        return RawEvent(
            source_name="eventbrite",
            source_tier="1_api",
            external_id=ev.get("id"),
            title=(ev.get("name") or {}).get("text"),
            category=_EB_CATEGORY.get(str(ev.get("category_id")), "community"),
            start_time=(ev.get("start") or {}).get("utc"),
            end_time=(ev.get("end") or {}).get("utc"),
            lat=float(lat) if lat is not None else None,
            lng=float(lng) if lng is not None else None,
            address=address,
            cost_tier="free" if ev.get("is_free") else "€€",
        )


class PredictHQSource:
    name = "predicthq"

    def __init__(self, settings: Settings) -> None:
        if not settings.predicthq_token:
            raise RuntimeError("PredictHQ needs PREDICTHQ_TOKEN")
        self._settings = settings

    async def fetch(self) -> list[RawEvent]:  # pragma: no cover - needs credentials
        # GET /v1/events/ with within=<radius>@<lat>,<lng> + active.gte/lte; same retry/map shape.
        raise NotImplementedError("Wire PredictHQ fetch like EventbriteSource, map → RawEvent")
