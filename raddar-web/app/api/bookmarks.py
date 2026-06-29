"""Bookmark API — the canonical high-intent action that triggers the Lazy Wall.

All mutations require an authenticated session (else 401 + login_url) and a valid CSRF token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth.deps import require_user, require_user_csrf
from app.db.deps import get_bookmark_store
from app.db.users import BookmarkStore, User

router = APIRouter(prefix="/api/bookmarks", tags=["bookmarks"])


class BookmarkIn(BaseModel):
    event_id: str


@router.get("")
async def list_bookmarks(
    user: User = Depends(require_user),
    store: BookmarkStore = Depends(get_bookmark_store),
) -> dict:
    return {"event_ids": await store.list(user.id)}


@router.post("", status_code=201)
async def add_bookmark(
    payload: BookmarkIn,
    user: User = Depends(require_user_csrf),
    store: BookmarkStore = Depends(get_bookmark_store),
) -> dict:
    await store.add(user.id, payload.event_id)
    return {"event_ids": await store.list(user.id)}


@router.delete("/{event_id}")
async def remove_bookmark(
    event_id: str,
    user: User = Depends(require_user_csrf),
    store: BookmarkStore = Depends(get_bookmark_store),
) -> dict:
    await store.remove(user.id, event_id)
    return {"event_ids": await store.list(user.id)}
