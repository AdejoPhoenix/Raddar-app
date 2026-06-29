"""In-process scheduler — runs the pipeline on a fixed interval.

Dependency-free alternative to system/Render cron for long-running hosts. A failed run is
logged and the loop continues (the next tick retries).

    DB_BACKEND=postgres python -m app.pipeline.schedule
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.config import get_settings
from app.pipeline.run import build_geocoder, build_sources, run_pipeline


async def run_forever() -> None:
    settings = get_settings()
    interval = settings.pipeline_interval_seconds
    logger.info("pipeline scheduler starting — every {}s", interval)
    while True:
        try:
            await run_pipeline(
                build_sources(settings),
                settings=settings,
                geocoder=build_geocoder(settings),
            )
        except Exception:  # noqa: BLE001 — never let one bad run kill the loop
            logger.exception("pipeline run failed; continuing")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
