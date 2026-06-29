"""User + bookmark stores for the Lazy Wall.

Async interfaces so the in-memory dev backend and the Postgres backend are interchangeable.
The in-memory singletons keep dev/tests credential- and DB-free; Postgres impls live in
`app/db/postgres.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field


class User(BaseModel):
    id: str
    provider: str  # "google" | "apple" | "mock"
    subject: str  # provider's stable user id
    email: str | None = None
    name: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserStore(Protocol):
    async def upsert(
        self, *, provider: str, subject: str, email: str | None, name: str | None
    ) -> User: ...

    async def get(self, user_id: str) -> User | None: ...


class BookmarkStore(Protocol):
    async def add(self, user_id: str, event_id: str) -> None: ...
    async def remove(self, user_id: str, event_id: str) -> None: ...
    async def list(self, user_id: str) -> list[str]: ...


class InMemoryUserStore:
    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}
        self._by_identity: dict[tuple[str, str], User] = {}

    async def upsert(
        self, *, provider: str, subject: str, email: str | None, name: str | None
    ) -> User:
        existing = self._by_identity.get((provider, subject))
        if existing is not None:
            return existing
        user = User(
            id=uuid.uuid4().hex, provider=provider, subject=subject, email=email, name=name
        )
        self._by_id[user.id] = user
        self._by_identity[(provider, subject)] = user
        return user

    async def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)


class InMemoryBookmarkStore:
    def __init__(self) -> None:
        self._store: dict[str, list[str]] = {}

    async def add(self, user_id: str, event_id: str) -> None:
        bucket = self._store.setdefault(user_id, [])
        if event_id not in bucket:
            bucket.append(event_id)

    async def remove(self, user_id: str, event_id: str) -> None:
        bucket = self._store.get(user_id)
        if bucket and event_id in bucket:
            bucket.remove(event_id)

    async def list(self, user_id: str) -> list[str]:
        return list(self._store.get(user_id, []))


# Process-wide singletons for the in-memory dev backend.
users: InMemoryUserStore = InMemoryUserStore()
bookmarks: InMemoryBookmarkStore = InMemoryBookmarkStore()
