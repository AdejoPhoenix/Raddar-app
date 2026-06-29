"""Unit tests for the shared Now-and-Next + geofence logic (pure, deterministic)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.geo import haversine_miles, within_radius
from app.core.service import discover
from app.core.temporal import in_now_and_next_window, is_expired
from app.config import Settings
from app.db.repository import InMemoryRepository
from app.models import Category, CostTier, Event, SourceTier

UTC = timezone.utc


def _event(*, start_min: int, dur_min: int, lat: float, lng: float) -> Event:
    now = datetime.now(UTC)
    start = now + timedelta(minutes=start_min)
    return Event(
        event_id="t",
        title="Test",
        category=Category.music,
        start_time=start,
        end_time=start + timedelta(minutes=dur_min),
        lat=lat,
        lng=lng,
        cost_tier=CostTier.free,
        source_tier=SourceTier.editorial,
    )


def test_active_now_passes_window() -> None:
    e = _event(start_min=-10, dur_min=60, lat=53.35, lng=-6.26)
    assert in_now_and_next_window(e, hours=3)


def test_starting_within_window_passes() -> None:
    e = _event(start_min=120, dur_min=60, lat=53.35, lng=-6.26)
    assert in_now_and_next_window(e, hours=3)


def test_too_far_in_future_excluded() -> None:
    e = _event(start_min=240, dur_min=60, lat=53.35, lng=-6.26)
    assert not in_now_and_next_window(e, hours=3)


def test_expired_detected() -> None:
    e = _event(start_min=-120, dur_min=30, lat=53.35, lng=-6.26)
    assert is_expired(e)


def test_haversine_known_distance() -> None:
    # ~0.69 miles between these two Dublin points (sanity range check)
    d = haversine_miles(53.3498, -6.2603, 53.3498, -6.2440)
    assert 0.5 < d < 0.9


def test_within_radius_boundary() -> None:
    assert within_radius(53.35, -6.26, 53.351, -6.261, 1.0)
    assert not within_radius(53.35, -6.26, 53.50, -6.26, 1.0)


@pytest.mark.asyncio
async def test_discover_returns_seeded_events_near_anchor() -> None:
    settings = Settings(db_backend="memory")
    repo = InMemoryRepository(settings)
    results = await discover(repo, settings, lat=settings.anchor_lat, lng=settings.anchor_lng)
    assert results, "expected seeded Dublin events within window + geofence"
    # sorted soonest-ending first
    mins = [r.minutes_until_end for r in results]
    assert mins == sorted(mins)
