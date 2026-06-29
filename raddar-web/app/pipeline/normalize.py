"""Normalize a RawEvent into the canonical Event.

Pipeline of guarantees enforced here:
  * category/cost strings mapped to canonical enums (unmappable category → reject)
  * times parsed to tz-aware UTC; missing end_time → per-category default duration
  * coordinates required — geocode from address if absent, else reject
  * coordinates must fall inside the Dublin bounding box, else reject (catches bad geocodes)
  * deterministic event_id derived from the dedup key, so the same event from different
    sources collides into one row (cross-source dedup for free on upsert)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.core.geo import within_bbox
from app.models import Category, CostTier, Event
from app.pipeline.geocode import Geocoder
from app.pipeline.schema import NormalizationError, RawEvent

_CATEGORY_SYNONYMS = {
    "music": Category.music, "gig": Category.music, "concert": Category.music,
    "live music": Category.music, "trad": Category.music, "session": Category.music,
    "food": Category.food, "street food": Category.food, "restaurant": Category.food,
    "market": Category.market, "pop-up": Category.market, "popup": Category.market,
    "flea": Category.market, "fair": Category.market,
    "art": Category.art, "gallery": Category.art, "exhibition": Category.art,
    "nightlife": Category.nightlife, "club": Category.nightlife, "bar": Category.nightlife,
    "sports": Category.sports, "sport": Category.sports, "match": Category.sports,
    "community": Category.community, "meetup": Category.community, "workshop": Category.community,
}

_COST_SYNONYMS = {
    "free": CostTier.free, "0": CostTier.free,
    "€": CostTier.low, "low": CostTier.low, "$": CostTier.low,
    "€€": CostTier.mid, "mid": CostTier.mid, "$$": CostTier.mid,
    "€€€": CostTier.high, "high": CostTier.high, "$$$": CostTier.high,
}

# default event length when a source omits end_time (minutes, by category)
_DEFAULT_DURATION = {
    Category.music: 150, Category.food: 180, Category.market: 240, Category.art: 240,
    Category.nightlife: 240, Category.sports: 120, Category.community: 120,
}


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _map_category(raw: str | None) -> Category:
    if not raw:
        raise NormalizationError("missing category")
    mapped = _CATEGORY_SYNONYMS.get(raw.strip().lower())
    if mapped is None:
        raise NormalizationError(f"unmappable category: {raw!r}")
    return mapped


def _map_cost(raw: str | None) -> CostTier:
    if not raw:
        return CostTier.free
    return _COST_SYNONYMS.get(raw.strip().lower(), CostTier.free)


def _dedup_event_id(title_normalized: str, start: datetime, lat: float, lng: float) -> str:
    key = f"{title_normalized}|{start.isoformat()}|{round(lat, 4)}|{round(lng, 4)}"
    return hashlib.sha1(key.encode()).hexdigest()[:16]


async def normalize(raw: RawEvent, *, geocoder: Geocoder, settings: Settings) -> Event:
    if not raw.title or not raw.title.strip():
        raise NormalizationError("missing title")
    if not raw.start_time:
        raise NormalizationError("missing start_time")

    category = _map_category(raw.category)
    start = _parse_dt(raw.start_time)
    end = (
        _parse_dt(raw.end_time)
        if raw.end_time
        else start + timedelta(minutes=_DEFAULT_DURATION[category])
    )
    if end <= start:
        raise NormalizationError("end_time not after start_time")

    lat, lng = raw.lat, raw.lng
    if (lat is None or lng is None) and raw.address:
        resolved = await geocoder.geocode(raw.address)
        if resolved is not None:
            lat, lng = resolved
    if lat is None or lng is None:
        raise NormalizationError("no coordinates (and address not resolvable)")

    if not within_bbox(
        lat, lng,
        min_lat=settings.bbox_min_lat, max_lat=settings.bbox_max_lat,
        min_lng=settings.bbox_min_lng, max_lng=settings.bbox_max_lng,
    ):
        raise NormalizationError(f"coordinates outside Dublin bbox: {lat},{lng}")

    title_normalized = raw.title.strip().lower()
    return Event(
        event_id=_dedup_event_id(title_normalized, start, lat, lng),
        title=raw.title.strip(),
        title_normalized=title_normalized,
        category=category,
        start_time=start,
        end_time=end,
        lat=lat,
        lng=lng,
        cost_tier=_map_cost(raw.cost_tier),
        source_tier=raw.source_tier,
        source_name=raw.source_name,
        expires_at=end,
    )
