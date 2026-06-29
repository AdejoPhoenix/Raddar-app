"""Session introspection — the client calls this to know auth state and get its CSRF token."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.auth.deps import current_user, ensure_csrf_token
from app.config import Settings, get_settings
from app.db.deps import get_event_repo
from app.db.repository import EventRepository
from app.db.users import User

router = APIRouter(prefix="/api", tags=["session"])


@router.get("/session")
async def session_info(
    request: Request,
    user: User | None = Depends(current_user),
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> dict:
    # so the client can show the hosting quota proactively (e.g. "4 of 5 used")
    hosting = None
    if user is not None:
        hosting = {
            "used": await repo.count_active_by_user(user.id),
            "limit": settings.host_max_active_per_user,
        }
    return {
        "authenticated": user is not None,
        "user": (
            {"id": user.id, "name": user.name, "email": user.email} if user else None
        ),
        "csrf_token": ensure_csrf_token(request),
        "hosting": hosting,
    }
