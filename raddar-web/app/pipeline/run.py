"""Pipeline orchestrator: fetch (concurrent) → normalize → dedup → upsert → purge → log.

Idempotent and failure-isolated: one source failing doesn't sink the others, and malformed
records are dead-lettered (logged) rather than aborting the run.

CLI:  DB_BACKEND=postgres python -m app.pipeline.run [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from app.config import Settings, get_settings
from app.db.base import session_factory
from app.models import Event
from app.pipeline.geocode import Geocoder, GoogleGeocoder, NoopGeocoder
from app.pipeline.normalize import normalize
from app.pipeline.schema import NormalizationError, RawEvent
from app.pipeline.scrapers import build_firecrawl_source
from app.pipeline.sources import EventbriteSource, EventSource, FixtureSource
from app.pipeline.writer import purge_expired, upsert_events


@dataclass
class RunStats:
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_duplicate: int = 0
    rejected: int = 0
    purged: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__


async def _fetch_all(sources: list[EventSource]) -> tuple[list[RawEvent], list[str]]:
    """Fetch every source concurrently; isolate failures (one dead source ≠ dead run)."""
    raws: list[RawEvent] = []
    errors: list[str] = []
    results = await asyncio.gather(*(s.fetch() for s in sources), return_exceptions=True)
    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            msg = f"source {source.name} failed: {result}"
            logger.warning(msg)
            errors.append(msg)
        else:
            raws.extend(result)
    return raws, errors


async def run_pipeline(
    sources: list[EventSource],
    *,
    settings: Settings,
    geocoder: Geocoder | None = None,
    dry_run: bool = False,
) -> RunStats:
    started = time.monotonic()
    geocoder = geocoder or NoopGeocoder()
    stats = RunStats()

    raws, stats.errors = await _fetch_all(sources)
    stats.fetched = len(raws)

    # normalize + dead-letter; dedup within the batch by event_id (the dedup hash)
    by_id: dict[str, Event] = {}
    for raw in raws:
        try:
            event = await normalize(raw, geocoder=geocoder, settings=settings)
        except NormalizationError as exc:
            stats.rejected += 1
            logger.warning("rejected ({}): {}", raw.source_name, exc)
            continue
        if event.event_id in by_id:
            stats.skipped_duplicate += 1
            continue
        by_id[event.event_id] = event

    events = list(by_id.values())

    if dry_run:
        logger.info("[dry-run] would upsert {} events; skipping DB writes", len(events))
        stats.duration_seconds = round(time.monotonic() - started, 3)
        logger.info("pipeline {}", stats.as_dict())
        return stats

    async with session_factory()() as session:
        stats.inserted, stats.updated = await upsert_events(session, events)
        stats.purged = await purge_expired(session)

    stats.duration_seconds = round(time.monotonic() - started, 3)
    logger.info("pipeline {}", stats.as_dict())
    return stats


def build_sources(settings: Settings) -> list[EventSource]:
    """Enable real Tier-1/2 sources when credentials are present; fall back to the fixture."""
    sources: list[EventSource] = []
    if settings.eventbrite_token and settings.eventbrite_organization_id:
        sources.append(EventbriteSource(settings))
    if settings.predicthq_token:
        from app.pipeline.sources import PredictHQSource

        sources.append(PredictHQSource(settings))
    if settings.firecrawl_api_key:
        sources.append(build_firecrawl_source(settings))
    if not sources:
        fixture = Path(__file__).parent / "fixtures" / "dublin_sample.json"
        sources.append(FixtureSource(fixture, name="dublin_fixture"))
        logger.info("no source credentials set — using bundled Dublin fixture")
    return sources


def build_geocoder(settings: Settings) -> Geocoder:
    """Real geocoder when a key is present (scraped events usually lack coordinates)."""
    if settings.google_geocoding_key:
        return GoogleGeocoder(settings, settings.google_geocoding_key)
    return NoopGeocoder()


async def _main(dry_run: bool) -> None:
    settings = get_settings()
    await run_pipeline(
        build_sources(settings),
        settings=settings,
        geocoder=build_geocoder(settings),
        dry_run=dry_run,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Raddar ingestion pipeline")
    parser.add_argument("--dry-run", action="store_true", help="normalize but don't write")
    args = parser.parse_args()
    asyncio.run(_main(args.dry_run))
