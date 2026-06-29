"""EventbriteSource + retry helper — mocked at the HTTP transport layer (no real API)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.pipeline.http import request_with_retry
from app.pipeline.normalize import normalize
from app.pipeline.geocode import NoopGeocoder
from app.pipeline.sources import EventbriteSource


def _settings() -> Settings:
    return Settings(eventbrite_token="tok", eventbrite_organization_id="org123")


def _make_source(handler) -> EventbriteSource:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://www.eventbriteapi.com/v3"
    )
    return EventbriteSource(_settings(), client=client)


def _event(eid: str, *, online=False, lat="53.34", lng="-6.26", free=True, cat="103") -> dict:
    return {
        "id": eid,
        "name": {"text": f"Event {eid}"},
        "category_id": cat,
        "start": {"utc": "2030-09-01T19:00:00Z"},
        "end": {"utc": "2030-09-01T21:00:00Z"},
        "online_event": online,
        "is_free": free,
        "venue": {
            "latitude": lat,
            "longitude": lng,
            "address": {"localized_address_display": "Somewhere, Dublin"},
        },
    }


@pytest.mark.asyncio
async def test_paginates_and_drops_online_events() -> None:
    page1 = {
        "events": [_event("a"), _event("online", online=True)],
        "pagination": {"has_more_items": True, "continuation": "cont1"},
    }
    page2 = {
        "events": [_event("b", free=False, cat="110")],
        "pagination": {"has_more_items": False},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("continuation") == "cont1":
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    raws = await _make_source(handler).fetch()
    ids = {r.external_id for r in raws}
    assert ids == {"a", "b"}  # online event dropped, both pages fetched
    eb_b = next(r for r in raws if r.external_id == "b")
    assert eb_b.category == "food" and eb_b.cost_tier == "€€"


@pytest.mark.asyncio
async def test_raw_maps_into_canonical_event() -> None:
    payload = {"events": [_event("a")], "pagination": {"has_more_items": False}}
    raws = await _make_source(lambda r: httpx.Response(200, json=payload)).fetch()
    event = await normalize(raws[0], geocoder=NoopGeocoder(), settings=_settings())
    assert event.category.value == "Music"
    assert round(event.lat, 2) == 53.34
    assert event.source_name == "eventbrite"


@pytest.mark.asyncio
async def test_retry_recovers_from_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://x") as client:
        resp = await request_with_retry(client, "GET", "/y", base_delay=0.001)
    assert resp.status_code == 200
    assert calls["n"] == 2  # retried once after the 429
