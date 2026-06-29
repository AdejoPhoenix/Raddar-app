"""AirtableRepository tests — mocked at the HTTP transport layer (httpx.MockTransport).

Verifies pagination, field→Event mapping, and that malformed records are rejected
(dead-lettered) rather than corrupting the result set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import Settings
from app.db.repository import AirtableRepository

UTC = timezone.utc


def _iso(minutes_from_now: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes_from_now)).isoformat()


def _settings() -> Settings:
    return Settings(
        db_backend="airtable",
        airtable_api_key="key123",
        airtable_base_id="appTEST",
        airtable_table="Events",
    )


def _make_repo(handler) -> AirtableRepository:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://api.airtable.com/v0/appTEST")
    return AirtableRepository(_settings(), client=client)


@pytest.mark.asyncio
async def test_parses_and_paginates() -> None:
    page1 = {
        "records": [
            {
                "id": "rec1",
                "fields": {
                    "event_id": "e1",
                    "title": "Gig",
                    "category": "Music",
                    "start_time": _iso(-10),
                    "end_time": _iso(50),
                    "lat": 53.35,
                    "lng": -6.26,
                    "cost_tier": "€€",
                    "expires_at": _iso(50),
                },
            }
        ],
        "offset": "next",
    }
    page2 = {
        "records": [
            {
                "id": "rec2",
                "fields": {
                    "title": "Market",  # no event_id → falls back to record id
                    "category": "Market",
                    "start_time": _iso(20),
                    # no end_time → default duration applied
                    "lat": 53.34,
                    "lng": -6.27,
                },
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "offset" in request.url.params:
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    repo = _make_repo(handler)
    events = await repo.list_active()
    assert {e.event_id for e in events} == {"e1", "rec2"}
    e1 = next(e for e in events if e.event_id == "e1")
    assert e1.cost_tier.value == "€€"
    e2 = next(e for e in events if e.event_id == "rec2")
    assert e2.end_time > e2.start_time  # default duration filled in


@pytest.mark.asyncio
async def test_malformed_record_is_dead_lettered_not_fatal() -> None:
    payload = {
        "records": [
            {"id": "good", "fields": {
                "title": "OK", "category": "Food",
                "start_time": _iso(0), "end_time": _iso(60),
                "lat": 53.35, "lng": -6.26,
            }},
            {"id": "bad-category", "fields": {
                "title": "Nope", "category": "NotARealCategory",
                "start_time": _iso(0), "end_time": _iso(60),
                "lat": 53.35, "lng": -6.26,
            }},
            {"id": "missing-coords", "fields": {
                "title": "Nope2", "category": "Art",
                "start_time": _iso(0), "end_time": _iso(60),
            }},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    repo = _make_repo(handler)
    events = await repo.list_active()
    # only the valid record survives; the two malformed ones are dropped
    assert [e.event_id for e in events] == ["good"]


@pytest.mark.asyncio
async def test_expired_records_excluded() -> None:
    payload = {
        "records": [
            {"id": "live", "fields": {
                "title": "Live", "category": "Music",
                "start_time": _iso(-30), "end_time": _iso(30),
                "lat": 53.35, "lng": -6.26,
            }},
            {"id": "over", "fields": {
                "title": "Over", "category": "Music",
                "start_time": _iso(-120), "end_time": _iso(-60),
                "lat": 53.35, "lng": -6.26,
            }},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    repo = _make_repo(handler)
    events = await repo.list_active()
    assert [e.event_id for e in events] == ["live"]
