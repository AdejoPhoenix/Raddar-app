"""Geocoding — resolve an address to coordinates when a source omits lat/lng.

`NoopGeocoder` (default) resolves nothing. `FixtureGeocoder` resolves known strings for
dev/tests. `GoogleGeocoder` is the real implementation (stub; needs an API key) and biases
results to the Dublin bounding box to avoid ambiguous matches.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings


class Geocoder(Protocol):
    async def geocode(self, address: str) -> tuple[float, float] | None: ...


class NoopGeocoder:
    async def geocode(self, address: str) -> tuple[float, float] | None:
        return None


class FixtureGeocoder:
    """Deterministic lookups for tests/dev — no network."""

    def __init__(self, table: dict[str, tuple[float, float]] | None = None) -> None:
        self._table = {k.lower(): v for k, v in (table or {}).items()}

    async def geocode(self, address: str) -> tuple[float, float] | None:
        return self._table.get(address.lower())


class GoogleGeocoder:
    _URL = "https://maps.googleapis.com/maps/api/geocode/json"

    def __init__(self, settings: Settings, api_key: str) -> None:
        self._settings = settings
        self._key = api_key

    async def geocode(self, address: str) -> tuple[float, float] | None:  # pragma: no cover
        s = self._settings
        params = {
            "address": address,
            "key": self._key,
            # bias to Dublin bounding box
            "bounds": f"{s.bbox_min_lat},{s.bbox_min_lng}|{s.bbox_max_lat},{s.bbox_max_lng}",
            "region": "ie",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        loc = data["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
