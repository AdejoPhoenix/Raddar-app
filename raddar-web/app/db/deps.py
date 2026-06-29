"""Backend-selection dependencies.

One place decides — per request — whether events/users/bookmarks come from Postgres, the
in-memory dev store, or (events only) Airtable. Everything downstream just gets an interface.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import get_session
from app.db.postgres import (
    PostgresBookmarkStore,
    PostgresEventRepository,
    PostgresUserStore,
)
from app.db.repository import EventRepository, get_repository
from app.db.users import BookmarkStore, UserStore, bookmarks, users


def get_event_repo(
    session: AsyncSession | None = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> EventRepository:
    if settings.db_backend == "postgres":
        assert session is not None
        return PostgresEventRepository(session)
    return get_repository(settings)  # memory | airtable


def get_user_store(
    session: AsyncSession | None = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserStore:
    if settings.db_backend == "postgres":
        assert session is not None
        return PostgresUserStore(session)
    return users


def get_bookmark_store(
    session: AsyncSession | None = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> BookmarkStore:
    if settings.db_backend == "postgres":
        assert session is not None
        return PostgresBookmarkStore(session)
    return bookmarks
