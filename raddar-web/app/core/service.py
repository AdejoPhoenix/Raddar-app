"""Discovery service — the single place that applies Now-and-Next + geofence.

Both the JSON API and the server-rendered pages call this, so web and (future) mobile
share identical filtering. Keep the rules here, never in a client.
"""

from __future__ import annotations

from app.config import Settings
from app.core.geo import within_radius
from app.core.temporal import in_now_and_next_window, is_expired
from app.db.repository import EventRepository
from app.models import Event, EventOut


async def discover(
    repo: EventRepository,
    settings: Settings,
    *,
    lat: float,
    lng: float,
) -> list[EventOut]:
    """Events active now or within the Now-and-Next window AND inside the 1-mile geofence."""
    candidates = await repo.list_active()
    results: list[EventOut] = []
    for e in candidates:
        if is_expired(e):
            continue
        if not in_now_and_next_window(e, hours=settings.now_and_next_hours):
            continue
        if not within_radius(lat, lng, e.lat, e.lng, settings.geofence_miles):
            continue
        results.append(EventOut.from_event(e, urgency_minutes=settings.urgency_minutes))
    # soonest-ending first → urgency surfaces at the top
    results.sort(key=lambda o: o.minutes_until_end)
    return results


async def get_event(repo: EventRepository, event_id: str) -> Event | None:
    return await repo.get(event_id)
