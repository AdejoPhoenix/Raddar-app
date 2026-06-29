"""Postgres integration tests for the async SQLAlchemy repositories.

Skipped automatically if a local Postgres test DB isn't reachable, so the suite still runs
in environments without Postgres. Point at a throwaway DB via TEST_DATABASE_URL.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.orm import EventRow  # noqa: F401 — register models on Base.metadata
from app.db.postgres import (
    PostgresBookmarkStore,
    PostgresEventRepository,
    PostgresUserStore,
)
from app.models import Category, CostTier, Event, SourceTier

UTC = timezone.utc
TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/raddar_test"
)


async def _make_session():
    engine = create_async_engine(TEST_URL, future=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover - environment without PG
        await engine.dispose()
        pytest.skip(f"Postgres not reachable at {TEST_URL}: {exc}")
    # clean slate each test
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE bookmarks, users, events RESTART IDENTITY CASCADE"))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _event(event_id: str, *, start_min: int, dur_min: int) -> Event:
    start = datetime.now(UTC) + timedelta(minutes=start_min)
    return Event(
        event_id=event_id,
        title="PG Test",
        category=Category.music,
        start_time=start,
        end_time=start + timedelta(minutes=dur_min),
        lat=53.35,
        lng=-6.26,
        cost_tier=CostTier.free,
        source_tier=SourceTier.editorial,
        source_name="seed",
    )


@pytest.mark.asyncio
async def test_event_repo_roundtrip_and_expiry() -> None:
    engine, Session = await _make_session()
    try:
        async with Session() as s:
            s.add(EventRow.from_event(_event("live", start_min=-10, dur_min=60)))
            s.add(EventRow.from_event(_event("over", start_min=-120, dur_min=30)))
            await s.commit()

        async with Session() as s:
            repo = PostgresEventRepository(s)
            ids = {e.event_id for e in await repo.list_active()}
            assert ids == {"live"}  # expired "over" excluded
            assert (await repo.get("live")).title == "PG Test"
            assert await repo.get("missing") is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_user_upsert_is_idempotent() -> None:
    engine, Session = await _make_session()
    try:
        async with Session() as s:
            store = PostgresUserStore(s)
            u1 = await store.upsert(provider="mock", subject="mock:x", email="x@e.com", name="X")
            u2 = await store.upsert(provider="mock", subject="mock:x", email="x@e.com", name="X")
            assert u1.id == u2.id  # same identity → same row
            assert (await store.get(u1.id)).name == "X"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bookmark_add_list_remove() -> None:
    engine, Session = await _make_session()
    try:
        async with Session() as s:
            user = await PostgresUserStore(s).upsert(
                provider="mock", subject="mock:b", email=None, name="B"
            )
            store = PostgresBookmarkStore(s)
            await store.add(user.id, "evt-1")
            await store.add(user.id, "evt-1")  # idempotent
            await store.add(user.id, "evt-2")
            assert await store.list(user.id) == ["evt-1", "evt-2"]
            await store.remove(user.id, "evt-1")
            assert await store.list(user.id) == ["evt-2"]
    finally:
        await engine.dispose()
