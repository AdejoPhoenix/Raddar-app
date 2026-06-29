"""Temporal filtering — the Now-and-Next rule lives here, identical for web and mobile.

An event passes the window if it is active *now* OR starts within `now_and_next_hours`.
Computed in UTC; the caller is responsible for storing tz-aware UTC datetimes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import Event


def in_now_and_next_window(event: Event, *, hours: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    horizon = now + timedelta(hours=hours)
    # active now: started already and not yet ended
    active_now = event.start_time <= now <= event.end_time
    # starting soon: starts between now and the horizon
    starting_soon = now < event.start_time <= horizon
    return active_now or starting_soon


def is_expired(event: Event, *, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if event.expires_at is not None:
        return event.expires_at <= now
    return event.end_time <= now
