"""Raw source record + the loose→canonical normalization contract.

Sources hand back `RawEvent` (permissive); the pipeline normalizes each into the canonical
`Event`. Anything that can't be normalized raises `NormalizationError` and is dead-lettered.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models import SourceTier


class NormalizationError(Exception):
    """Raised when a raw record can't be turned into a valid canonical Event."""


class RawEvent(BaseModel):
    """Permissive shape returned by sources. Unknown keys are ignored."""

    model_config = ConfigDict(extra="ignore")

    source_name: str
    source_tier: SourceTier = SourceTier.api
    external_id: str | None = None
    title: str | None = None
    category: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    lat: float | None = None
    lng: float | None = None
    address: str | None = None
    cost_tier: str | None = None
