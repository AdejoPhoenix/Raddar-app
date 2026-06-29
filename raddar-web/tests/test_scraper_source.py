"""Tier-2 ScraperSource + FirecrawlProvider — mocked HTTP, plus the scraped→canonical path."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.pipeline.geocode import FixtureGeocoder
from app.pipeline.normalize import normalize
from app.pipeline.scrapers import EVENT_SCHEMA, FirecrawlProvider, ScraperSource


def _firecrawl_response(events: list[dict]) -> dict:
    return {"success": True, "data": {"json": {"events": events}}}


@pytest.mark.asyncio
async def test_firecrawl_provider_extracts_events() -> None:
    payload = _firecrawl_response(
        [{"title": "Trad night", "category": "music", "start_time": "2030-09-01T20:00:00Z"}]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/scrape"
        body = request.read().decode()
        assert "jsonOptions" in body  # schema/prompt forwarded
        return httpx.Response(200, json=payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.firecrawl.dev") as c:
        provider = FirecrawlProvider("fc-key", client=c)
        events = await provider.extract(
            "https://example.com", schema=EVENT_SCHEMA, prompt="x"
        )
    assert events[0]["title"] == "Trad night"


class _StubProvider:
    def __init__(self, by_url: dict[str, list[dict]]) -> None:
        self._by_url = by_url

    async def extract(self, url, *, schema, prompt) -> list[dict]:
        return self._by_url.get(url, [])


class _FailingProvider:
    async def extract(self, url, *, schema, prompt) -> list[dict]:
        raise RuntimeError("site down")


@pytest.mark.asyncio
async def test_scraper_source_maps_records_to_rawevents() -> None:
    provider = _StubProvider(
        {
            "https://a.ie": [
                {"title": "Eatyard", "category": "food",
                 "start_time": "2030-09-01T17:00:00Z", "address": "Dublin 8", "cost": "free"}
            ]
        }
    )
    source = ScraperSource(provider, [{"site": "a", "url": "https://a.ie"}])
    raws = await source.fetch()
    assert len(raws) == 1
    assert raws[0].source_name == "scrape:a"
    assert raws[0].source_tier.value == "2_scrape"


@pytest.mark.asyncio
async def test_scraper_source_isolates_failing_site() -> None:
    provider = _FailingProvider()
    source = ScraperSource(provider, [{"site": "bad", "url": "https://bad.ie"}])
    assert await source.fetch() == []  # failure logged, not raised


@pytest.mark.asyncio
async def test_scraped_event_geocodes_and_normalizes() -> None:
    provider = _StubProvider(
        {
            "https://a.ie": [
                {"title": "Pop-up market", "category": "market",
                 "start_time": "2030-09-01T11:00:00Z", "address": "Francis St, Dublin"}
            ]
        }
    )
    raws = await ScraperSource(provider, [{"site": "a", "url": "https://a.ie"}]).fetch()
    geocoder = FixtureGeocoder({"francis st, dublin": (53.341, -6.273)})
    event = await normalize(raws[0], geocoder=geocoder, settings=Settings())
    assert event.category.value == "Market"
    assert round(event.lat, 3) == 53.341  # address resolved via geocoder
