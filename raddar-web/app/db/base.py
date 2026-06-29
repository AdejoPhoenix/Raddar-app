"""Async SQLAlchemy engine, session factory, and the request-scoped session dependency.

The engine is created lazily on first use so the app boots with zero DB cost when running
the in-memory backend. `get_session` yields a live AsyncSession only for the postgres
backend; other backends get `None` (they don't use SQL).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_local: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine, _session_local
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.sqlalchemy_url, future=True, pool_pre_ping=True)
        _session_local = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_local is not None
    return _session_local


async def init_models() -> None:
    """Create tables if absent (dev convenience; production uses migrations)."""
    from app.db import orm  # noqa: F401 — ensure models are registered on Base.metadata

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession | None]:
    settings = get_settings()
    if settings.db_backend != "postgres":
        yield None
        return
    async with session_factory()() as session:
        yield session
