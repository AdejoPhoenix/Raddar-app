"""Geographic helpers — the 1-mile geofence is enforced here, shared by all clients."""

from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

_EARTH_RADIUS_MILES = 3958.7613
_EARTH_RADIUS_METERS = 6_371_000.0


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Unit-less haversine term — multiply by an Earth radius for distance."""
    d_lat = radians(lat2 - lat1)
    d_lng = radians(lng2 - lng1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lng / 2) ** 2
    )
    return 2 * asin(sqrt(a))


def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two coordinates."""
    return _EARTH_RADIUS_MILES * _haversine(lat1, lng1, lat2, lng2)


def haversine_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres between two coordinates."""
    return _EARTH_RADIUS_METERS * _haversine(lat1, lng1, lat2, lng2)


def within_radius(
    center_lat: float, center_lng: float, lat: float, lng: float, radius_miles: float
) -> bool:
    return haversine_miles(center_lat, center_lng, lat, lng) <= radius_miles


def within_bbox(
    lat: float,
    lng: float,
    *,
    min_lat: float,
    max_lat: float,
    min_lng: float,
    max_lng: float,
) -> bool:
    """Used at ingest time to reject mis-geocoded coordinates (e.g. 'Dublin, Ohio')."""
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng
