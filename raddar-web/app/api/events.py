"""JSON read-API + user-hosted event creation."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.auth.deps import require_user_csrf
from app.config import Settings, get_settings
from app.core.geo import haversine_meters
from app.core.service import discover
from app.db.deps import get_event_repo
from app.db.repository import EventRepository
from app.db.users import User
from app.models import Category, CostTier, Event, EventOut, SourceTier

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events", response_model=list[EventOut])
async def list_events(
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> list[EventOut]:
    """Events within the Now-and-Next window and 1-mile geofence of (lat, lng).

    If location is omitted (geolocation denied), fall back to the Dublin city-centre anchor
    so the map is never empty.
    """
    center_lat = lat if lat is not None else settings.anchor_lat
    center_lng = lng if lng is not None else settings.anchor_lng
    return await discover(repo, settings, lat=center_lat, lng=center_lng)


class HostEventIn(BaseModel):
    """A user dropping a pin: 'this is happening here, starting now, for N minutes'.

    `lat`/`lng` is where the pin goes; `user_lat`/`user_lng` is the device's live GPS at submit
    time. The server requires the pin to sit within `host_radius_meters` of the live location,
    so users can only host near where they actually are.
    """

    title: str = Field(min_length=2, max_length=120)
    category: Category
    cost_tier: CostTier = CostTier.free
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    user_lat: float = Field(ge=-90, le=90)
    user_lng: float = Field(ge=-180, le=180)
    duration_minutes: int = Field(default=120, ge=15, le=720)


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def host_event(
    payload: HostEventIn,
    user: User = Depends(require_user_csrf),  # Lazy Wall: 401 + login_url when anonymous
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> EventOut:
    """Create a user-hosted event near the user, starting now.

    The pin must be within `host_radius_meters` of the user's live GPS — you can only host
    where you actually are, not in another part of town or another country.
    """
    distance = haversine_meters(payload.user_lat, payload.user_lng, payload.lat, payload.lng)
    if distance > settings.host_radius_meters:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Pin must be within {settings.host_radius_meters:.0f}m of your current "
                "location."
            ),
        )

    active = await repo.count_active_by_user(user.id)
    if active >= settings.host_max_active_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"You can have at most {settings.host_max_active_per_user} active pins. "
                "Wait for one to expire before hosting another."
            ),
        )

    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=payload.duration_minutes)
    event = Event(
        event_id=uuid.uuid4().hex,
        title=payload.title.strip(),
        category=payload.category,
        start_time=now,
        end_time=end,
        lat=payload.lat,
        lng=payload.lng,
        cost_tier=payload.cost_tier,
        source_tier=SourceTier.user,
        source_name=f"user:{user.id}",
        created_by=user.id,
        expires_at=end,
    )
    await repo.create(event)
    return EventOut.from_event(event, urgency_minutes=settings.urgency_minutes)


class HostEventEditIn(BaseModel):
    """Editable fields of a user's own pin. Location is fixed (it's GPS-tied), so it can't be
    moved here — only what/when. Any field left out is unchanged."""

    title: str | None = Field(default=None, min_length=2, max_length=120)
    category: Category | None = None
    cost_tier: CostTier | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=720)


async def _owned_event(event_id: str, user: User, repo: EventRepository) -> Event:
    """Load an event and assert the caller hosted it (404 if gone, 403 if not theirs)."""
    event = await repo.get(event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found or no longer active.")
    if event.created_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only manage pins you hosted.")
    return event


@router.patch("/events/{event_id}", response_model=EventOut)
async def edit_event(
    event_id: str,
    payload: HostEventEditIn,
    user: User = Depends(require_user_csrf),
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> EventOut:
    """Edit the what/when of a pin you hosted (not its location)."""
    event = await _owned_event(event_id, user, repo)

    updates: dict = {}
    if payload.title is not None:
        updates["title"] = payload.title.strip()
    if payload.category is not None:
        updates["category"] = payload.category
    if payload.cost_tier is not None:
        updates["cost_tier"] = payload.cost_tier
    if payload.duration_minutes is not None:
        # duration is relative to the original start; keep it pinned to "started now then"
        new_end = event.start_time + timedelta(minutes=payload.duration_minutes)
        updates["end_time"] = new_end
        updates["expires_at"] = new_end

    updated = event.model_copy(update=updates)
    await repo.update(updated)
    return EventOut.from_event(updated, urgency_minutes=settings.urgency_minutes)


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    user: User = Depends(require_user_csrf),
    repo: EventRepository = Depends(get_event_repo),
) -> Response:
    """Delete a pin you hosted."""
    await _owned_event(event_id, user, repo)  # 404 / 403 guard
    await repo.delete(event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
