"""Create tables and load the Dublin seed events into Postgres.

Usage:
    DB_BACKEND=postgres python -m scripts.seed_db

Idempotent: upserts by event_id, so re-running refreshes the seed set.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import delete

from app.config import get_settings
from app.db.base import init_models, session_factory
from app.db.orm import EventRow
from app.db.repository import _seed_events


async def main() -> None:
    settings = get_settings()
    await init_models()
    events = _seed_events(settings.anchor_lat, settings.anchor_lng)

    async with session_factory()() as session:
        # clear prior seed rows, then insert a fresh set
        await session.execute(delete(EventRow).where(EventRow.source_name == "seed"))
        for e in events:
            session.add(EventRow.from_event(e))
        await session.commit()

    print(f"Seeded {len(events)} events into {settings.database_url}")


if __name__ == "__main__":
    asyncio.run(main())
