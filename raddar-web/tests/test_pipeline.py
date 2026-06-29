"""Ingestion pipeline tests — normalization (no DB) + writer/idempotency (Postgres)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.orm import EventRow  # noqa: F401 — register models
from app.models import Event
from app.pipeline.geocode import FixtureGeocoder, NoopGeocoder
from app.pipeline.normalize import normalize
from app.pipeline.run import run_pipeline
from app.pipeline.schema import NormalizationError, RawEvent
from app.pipeline.writer import purge_expired, upsert_events

UTC = timezone.utc
SETTINGS = Settings()
TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/raddar_test")


# ---------- normalization (no DB) ----------

def _raw(**kw) -> RawEvent:
    base = dict(
        source_name="t", title="Gig", category="music",
        start_time="2030-01-01T20:00:00Z", lat=53.35, lng=-6.26,
    )
    base.update(kw)
    return RawEvent.model_validate(base)


@pytest.mark.asyncio
async def test_normalize_valid() -> None:
    e = await normalize(_raw(), geocoder=NoopGeocoder(), settings=SETTINGS)
    assert e.category.value == "Music"
    assert e.expires_at == e.end_time
    assert e.end_time > e.start_time  # default duration applied (no end_time given)


@pytest.mark.asyncio
async def test_normalize_rejects_bad_category() -> None:
    with pytest.raises(NormalizationError):
        await normalize(_raw(category="quantum-rave"), geocoder=NoopGeocoder(), settings=SETTINGS)


@pytest.mark.asyncio
async def test_normalize_rejects_outside_bbox() -> None:
    with pytest.raises(NormalizationError):
        await normalize(_raw(lat=51.50, lng=-0.12), geocoder=NoopGeocoder(), settings=SETTINGS)


@pytest.mark.asyncio
async def test_normalize_rejects_missing_fields() -> None:
    with pytest.raises(NormalizationError):
        await normalize(_raw(title=""), geocoder=NoopGeocoder(), settings=SETTINGS)
    with pytest.raises(NormalizationError):
        await normalize(_raw(start_time=None), geocoder=NoopGeocoder(), settings=SETTINGS)


@pytest.mark.asyncio
async def test_normalize_geocodes_address_when_no_coords() -> None:
    geocoder = FixtureGeocoder({"francis st, dublin": (53.341, -6.273)})
    e = await normalize(
        _raw(lat=None, lng=None, address="Francis St, Dublin"),
        geocoder=geocoder,
        settings=SETTINGS,
    )
    assert round(e.lat, 3) == 53.341


@pytest.mark.asyncio
async def test_dedup_id_is_stable_across_equivalent_records() -> None:
    a = await normalize(_raw(source_name="x"), geocoder=NoopGeocoder(), settings=SETTINGS)
    b = await normalize(_raw(source_name="y"), geocoder=NoopGeocoder(), settings=SETTINGS)
    assert a.event_id == b.event_id  # same title/time/coords → same id (cross-source dedup)


# ---------- orchestration (dry-run, no DB) ----------

class _InlineSource:
    def __init__(self, name: str, raws: list[RawEvent]) -> None:
        self.name = name
        self._raws = raws

    async def fetch(self) -> list[RawEvent]:
        return self._raws


class _FailingSource:
    name = "boom"

    async def fetch(self) -> list[RawEvent]:
        raise RuntimeError("source down")


@pytest.mark.asyncio
async def test_run_counts_and_failure_isolation() -> None:
    good = _InlineSource("good", [_raw(title="A"), _raw(title="B"), _raw(title="A")])  # A dup
    bad = _InlineSource("bad", [_raw(category="nope"), _raw(lat=51.5, lng=-0.1)])  # 2 rejects
    stats = await run_pipeline(
        [good, bad, _FailingSource()], settings=SETTINGS, dry_run=True
    )
    assert stats.fetched == 5
    assert stats.skipped_duplicate == 1
    assert stats.rejected == 2
    assert any("boom" in e for e in stats.errors)  # failing source isolated, not fatal


# ---------- writer (Postgres) ----------

async def _make_session():
    engine = create_async_engine(TEST_URL, future=True)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:  # pragma: no cover
        await engine.dispose()
        pytest.skip(f"Postgres not reachable: {exc}")
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE bookmarks, users, events RESTART IDENTITY CASCADE"))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _event(event_id: str, *, end_offset_min: int) -> Event:
    now = datetime.now(UTC)
    return Event(
        event_id=event_id, title="W", category="Music",
        start_time=now - timedelta(minutes=10),
        end_time=now + timedelta(minutes=end_offset_min),
        lat=53.35, lng=-6.26, expires_at=now + timedelta(minutes=end_offset_min),
    )


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_purge_removes_expired() -> None:
    engine, Session = await _make_session()
    try:
        async with Session() as s:
            ins, upd = await upsert_events(s, [_event("a", end_offset_min=60),
                                               _event("b", end_offset_min=60)])
            assert (ins, upd) == (2, 0)
        async with Session() as s:
            ins, upd = await upsert_events(s, [_event("a", end_offset_min=60)])
            assert (ins, upd) == (0, 1)  # re-run updates, never duplicates
        async with Session() as s:
            # add an already-expired event, then purge
            await upsert_events(s, [_event("old", end_offset_min=-30)])
            purged = await purge_expired(s)
            assert purged >= 1
    finally:
        await engine.dispose()
