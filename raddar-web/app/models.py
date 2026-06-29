"""Canonical event schema — the single contract shared across pipeline, API, and clients.

Mirrors IMPLEMENTATION_PLAN.md §2. The mobile app and web both consume this shape.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Category(str, Enum):
    music = "Music"
    food = "Food"
    market = "Market"
    art = "Art"
    nightlife = "Nightlife"
    sports = "Sports"
    community = "Community"


class CostTier(str, Enum):
    free = "Free"
    low = "€"
    mid = "€€"
    high = "€€€"


class SourceTier(str, Enum):
    api = "1_api"
    scrape = "2_scrape"
    editorial = "3_editorial"
    user = "4_user"  # hosted by a Raddar user (dropped a pin)


class Event(BaseModel):
    """A single discoverable event. Times are always timezone-aware UTC."""

    event_id: str
    title: str
    title_normalized: str = ""
    category: Category
    start_time: datetime
    end_time: datetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    cost_tier: CostTier = CostTier.free
    source_tier: SourceTier = SourceTier.editorial
    source_name: str = ""
    created_by: str | None = None  # user id, for user-hosted events
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_today(self) -> bool:
        """Server-side temporal truth — never delegated to the client."""
        return self.start_time.astimezone(timezone.utc).date() == datetime.now(timezone.utc).date()

    def model_post_init(self, __context: object) -> None:  # noqa: D105
        if not self.title_normalized:
            object.__setattr__(self, "title_normalized", self.title.strip().lower())


class EventOut(BaseModel):
    """Lean shape returned to the map client (no internal bookkeeping fields)."""

    event_id: str
    title: str
    category: Category
    start_time: datetime
    end_time: datetime
    lat: float
    lng: float
    cost_tier: CostTier
    minutes_until_end: int
    is_ending_soon: bool

    @classmethod
    def from_event(cls, e: Event, *, urgency_minutes: int) -> "EventOut":
        now = datetime.now(timezone.utc)
        minutes_until_end = max(0, int((e.end_time - now).total_seconds() // 60))
        return cls(
            event_id=e.event_id,
            title=e.title,
            category=e.category,
            start_time=e.start_time,
            end_time=e.end_time,
            lat=e.lat,
            lng=e.lng,
            cost_tier=e.cost_tier,
            minutes_until_end=minutes_until_end,
            is_ending_soon=0 < minutes_until_end <= urgency_minutes,
        )
