"""Application settings and Dublin launch-city configuration.

All values can be overridden via environment variables (see .env.example).
Dublin geo/temporal constants live here so both the API and templates use one source.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "Raddar"
    debug: bool = True

    # --- Data backend ---
    # "postgres" (operational DB) | "memory" (seeded dev data) | "airtable" (legacy read layer)
    db_backend: str = "memory"
    # Async SQLAlchemy URL (asyncpg driver). Omit user → uses the OS user (local peer auth).
    database_url: str = "postgresql+asyncpg://localhost:5432/raddar"
    # Dev convenience: create_all on startup. Set False in production and use Alembic migrations.
    auto_create_tables: bool = True
    airtable_api_key: str = ""
    airtable_base_id: str = ""
    airtable_table: str = "Events"

    # --- Launch city: Dublin, Ireland ---
    city_name: str = "Dublin"
    timezone: str = "Europe/Dublin"  # DST-aware; never hardcode a fixed UTC offset
    # City-centre anchor (O'Connell Bridge / Trinity College) — geolocation fallback
    anchor_lat: float = 53.3498
    anchor_lng: float = -6.2603
    # Pipeline/ingest bounding box (reject geocoded coords outside this)
    bbox_min_lat: float = 53.30
    bbox_max_lat: float = 53.41
    bbox_min_lng: float = -6.40
    bbox_max_lng: float = -6.10

    # --- Product rules ---
    geofence_miles: float = 1.0  # strict display radius
    now_and_next_hours: int = 3  # only events active now or starting within this window
    urgency_minutes: int = 30  # pulse pins ending within this many minutes
    refetch_seconds: int = 90  # client live re-fetch interval
    host_radius_meters: float = 70.0  # a hosted pin must be within this of the user's live GPS
    host_max_active_per_user: int = 5  # max concurrent (non-expired) pins one user may host

    # --- Sessions & auth (Lazy Wall) ---
    session_secret: str = "dev-insecure-secret-change-me"  # override in production!
    cookie_secure: bool = False  # True in production (HTTPS only)
    session_max_age: int = 60 * 60 * 24 * 30  # 30 days
    oauth_mock: bool = True  # use the built-in mock provider (no real creds needed)
    google_client_id: str = ""
    google_client_secret: str = ""
    apple_client_id: str = ""
    apple_client_secret: str = ""

    # --- Hardening (W5) ---
    rate_limit_per_minute: int = 120  # per-IP limit on /api/* endpoints

    # --- Ingestion pipeline ---
    eventbrite_token: str = ""
    eventbrite_organization_id: str = ""
    predicthq_token: str = ""
    firecrawl_api_key: str = ""  # Tier-2 scraping
    google_geocoding_key: str = ""
    pipeline_interval_seconds: int = 300  # scheduler cadence for live data

    @property
    def use_mock_oauth(self) -> bool:
        """Fall back to the mock provider whenever real credentials are absent."""
        return self.oauth_mock or not (self.google_client_id and self.google_client_secret)

    @property
    def sqlalchemy_url(self) -> str:
        """Normalize hosted `postgres://`/`postgresql://` URLs to the asyncpg driver.

        Render/Heroku hand out `postgres://...`; SQLAlchemy async needs `postgresql+asyncpg://`.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            return "postgresql+asyncpg://" + url[len("postgres://") :]
        if url.startswith("postgresql://"):
            return "postgresql+asyncpg://" + url[len("postgresql://") :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
