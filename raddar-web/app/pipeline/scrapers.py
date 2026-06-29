"""Tier-2 scraping source — structured event extraction from listings pages.

Uses Firecrawl's scrape+JSON-extract to pull events off Dublin sites (alt-news, brewery
calendars, tourism boards) that the Tier-1 APIs miss (food trucks, pop-ups, trad sessions).
Scraped output is untrusted → it flows through the same `RawEvent` → `normalize()` path, so
malformed/out-of-bbox records are rejected like any other source.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import httpx
from loguru import logger

from app.config import Settings
from app.pipeline.http import request_with_retry
from app.pipeline.schema import RawEvent

# JSON schema + prompt handed to the scraper's extractor.
EVENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "category": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO 8601 UTC"},
                    "end_time": {"type": "string", "description": "ISO 8601 UTC"},
                    "address": {"type": "string"},
                    "cost": {"type": "string"},
                },
                "required": ["title", "start_time"],
            },
        }
    },
}
EXTRACT_PROMPT = (
    "Extract upcoming in-person events on this page. Use ISO 8601 UTC for start_time/end_time. "
    "category must be one of: music, food, market, art, nightlife, sports, community. "
    "Include a street address when shown. Ignore online-only events."
)


class ScrapeProvider(Protocol):
    async def extract(self, url: str, *, schema: dict[str, Any], prompt: str) -> list[dict]: ...


class FirecrawlProvider:
    """Firecrawl scrape + JSON extraction. Returns the `events` array from a page."""

    _URL = "https://api.firecrawl.dev/v1/scrape"

    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = client

    async def extract(self, url: str, *, schema: dict[str, Any], prompt: str) -> list[dict]:
        client = self._client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._client is None
        body = {
            "url": url,
            "formats": ["json"],
            "jsonOptions": {"schema": schema, "prompt": prompt},
        }
        try:
            resp = await request_with_retry(
                client, "POST", self._URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns_client:
                await client.aclose()
        return (data.get("data", {}).get("json", {}) or {}).get("events", [])


class ScraperSource:
    """Drives a ScrapeProvider across configured target sites, mapping results → RawEvent."""

    def __init__(
        self,
        provider: ScrapeProvider,
        targets: list[dict[str, str]],
        *,
        name: str = "scraper",
    ) -> None:
        self.name = name
        self._provider = provider
        self._targets = targets

    @classmethod
    def from_config(cls, provider: ScrapeProvider, config_path: str | Path, **kw) -> "ScraperSource":
        targets = json.loads(Path(config_path).read_text())
        return cls(provider, targets, **kw)

    async def fetch(self) -> list[RawEvent]:
        raws: list[RawEvent] = []
        for target in self._targets:
            site, url = target["site"], target["url"]
            try:
                records = await self._provider.extract(url, schema=EVENT_SCHEMA, prompt=EXTRACT_PROMPT)
            except Exception as exc:  # noqa: BLE001 — one bad site shouldn't sink the rest
                logger.warning("scrape failed for {} ({}): {}", site, url, exc)
                continue
            for rec in records:
                raws.append(
                    RawEvent(
                        source_name=f"scrape:{site}",
                        source_tier="2_scrape",
                        title=rec.get("title"),
                        category=rec.get("category"),
                        start_time=rec.get("start_time"),
                        end_time=rec.get("end_time"),
                        address=rec.get("address"),
                        cost_tier=rec.get("cost"),
                    )
                )
        return raws


def default_targets_path() -> Path:
    return Path(__file__).parent / "fixtures" / "scrape_targets.json"


def build_firecrawl_source(settings: Settings) -> ScraperSource:
    return ScraperSource.from_config(
        FirecrawlProvider(settings.firecrawl_api_key),
        default_targets_path(),
        name="firecrawl",
    )
