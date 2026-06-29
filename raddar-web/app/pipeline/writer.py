"""Postgres writer — idempotent upsert + self-cleaning purge.

Upserts by `event_id` (which is the dedup hash), so re-running the pipeline never duplicates
rows. Returns precise counts so each run can be logged (inserted vs updated).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm import EventRow
from app.models import Event


def _values(e: Event) -> dict[str, Any]:
    return {
        "event_id": e.event_id,
        "title": e.title,
        "title_normalized": e.title_normalized,
        "category": e.category.value,
        "start_time": e.start_time,
        "end_time": e.end_time,
        "lat": e.lat,
        "lng": e.lng,
        "cost_tier": e.cost_tier.value,
        "source_tier": e.source_tier.value,
        "source_name": e.source_name,
        "created_at": e.created_at,
        "expires_at": e.expires_at,
    }


async def upsert_events(session: AsyncSession, events: list[Event]) -> tuple[int, int]:
    """Insert new events, update existing ones. Returns (inserted, updated)."""
    if not events:
        return (0, 0)

    ids = [e.event_id for e in events]
    existing = set(
        (await session.execute(select(EventRow.event_id).where(EventRow.event_id.in_(ids))))
        .scalars()
        .all()
    )

    for e in events:
        values = _values(e)
        stmt = pg_insert(EventRow).values(**values)
        # on conflict: refresh everything except the immutable identity + created_at
        update_cols = {
            k: stmt.excluded[k] for k in values if k not in ("event_id", "created_at")
        }
        stmt = stmt.on_conflict_do_update(index_elements=["event_id"], set_=update_cols)
        await session.execute(stmt)

    await session.commit()
    inserted = sum(1 for e in events if e.event_id not in existing)
    return (inserted, len(events) - inserted)


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Self-cleaning: delete rows past expiry. Returns the number purged."""
    now = now or datetime.now(timezone.utc)
    result = await session.execute(
        delete(EventRow).where(
            or_(
                EventRow.expires_at < now,
                and_(EventRow.expires_at.is_(None), EventRow.end_time < now),
            )
        )
    )
    await session.commit()
    return result.rowcount or 0
