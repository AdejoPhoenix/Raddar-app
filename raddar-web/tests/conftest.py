"""Test isolation.

App-logic tests (auth, bookmarks, session, hardening) must run against the in-memory backend
regardless of the developer's local .env (which may point DB_BACKEND at Postgres). Postgres
behavior is covered separately by tests that build their own engine explicitly
(test_postgres.py, the pipeline writer tests).

Setting the env var here — at conftest import, before any `app` import — overrides .env via
pydantic-settings precedence (env var > .env file).
"""

from __future__ import annotations

import os

os.environ["DB_BACKEND"] = "memory"
# Don't let local source credentials leak into source-selection logic under test.
os.environ["EVENTBRITE_TOKEN"] = ""
os.environ["EVENTBRITE_ORGANIZATION_ID"] = ""
os.environ["PREDICTHQ_TOKEN"] = ""
os.environ["FIRECRAWL_API_KEY"] = ""
os.environ["GOOGLE_GEOCODING_KEY"] = ""
