"""Postgres-backed repositories (async SQLAlchemy) for events, users, and bookmarks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm import BookmarkRow, EventRow, UserRow
from app.db.users import User
from app.models import Event


class PostgresEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active(self) -> list[Event]:
        now = datetime.now(timezone.utc)
        # non-expired: explicit expires_at in the future, or none set and not yet ended
        stmt = select(EventRow).where(
            or_(
                EventRow.expires_at > now,
                and_(EventRow.expires_at.is_(None), EventRow.end_time > now),
            )
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [row.to_event() for row in rows]

    async def get(self, event_id: str) -> Event | None:
        row = await self._session.get(EventRow, event_id)
        return row.to_event() if row else None

    async def create(self, event: Event) -> None:
        self._session.add(EventRow.from_event(event))
        await self._session.commit()

    @staticmethod
    def _not_expired(now: datetime):
        return or_(
            EventRow.expires_at > now,
            and_(EventRow.expires_at.is_(None), EventRow.end_time > now),
        )

    async def count_active_by_user(self, user_id: str) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            select(func.count())
            .select_from(EventRow)
            .where(EventRow.created_by == user_id, self._not_expired(now))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_by_user(self, user_id: str) -> list[Event]:
        now = datetime.now(timezone.utc)
        stmt = (
            select(EventRow)
            .where(EventRow.created_by == user_id, self._not_expired(now))
            .order_by(EventRow.end_time)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [row.to_event() for row in rows]

    async def update(self, event: Event) -> None:
        await self._session.merge(EventRow.from_event(event))  # upsert by primary key
        await self._session.commit()

    async def delete(self, event_id: str) -> None:
        await self._session.execute(delete(EventRow).where(EventRow.event_id == event_id))
        await self._session.commit()


class PostgresUserStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, provider: str, subject: str, email: str | None, name: str | None
    ) -> User:
        stmt = select(UserRow).where(UserRow.provider == provider, UserRow.subject == subject)
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing.to_user()
        row = UserRow(
            id=uuid.uuid4().hex,
            provider=provider,
            subject=subject,
            email=email,
            name=name,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        await self._session.commit()
        return row.to_user()

    async def get(self, user_id: str) -> User | None:
        row = await self._session.get(UserRow, user_id)
        return row.to_user() if row else None


class PostgresBookmarkStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user_id: str, event_id: str) -> None:
        existing = await self._session.get(BookmarkRow, {"user_id": user_id, "event_id": event_id})
        if existing is None:
            self._session.add(
                BookmarkRow(
                    user_id=user_id, event_id=event_id, created_at=datetime.now(timezone.utc)
                )
            )
            await self._session.commit()

    async def remove(self, user_id: str, event_id: str) -> None:
        await self._session.execute(
            delete(BookmarkRow).where(
                BookmarkRow.user_id == user_id, BookmarkRow.event_id == event_id
            )
        )
        await self._session.commit()

    async def list(self, user_id: str) -> list[str]:
        stmt = (
            select(BookmarkRow.event_id)
            .where(BookmarkRow.user_id == user_id)
            .order_by(BookmarkRow.created_at)
        )
        return list((await self._session.execute(stmt)).scalars().all())
