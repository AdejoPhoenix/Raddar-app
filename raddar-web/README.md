# Raddar Web

Web companion to the Raddar mobile app — **FastAPI + Jinja2 + MapLibre GL JS**.
See [`../IMPLEMENTATION_PLAN_WEB.md`](../IMPLEMENTATION_PLAN_WEB.md) for the full plan.

Two backends: **Postgres** (operational DB) or **memory** (seeded demo, no infra).

## Quickstart (memory — zero infra)

```bash
cd raddar-web
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # FastAPI, SQLAlchemy, asyncpg, pydantic, pytest...
uvicorn app.main:app --reload    # DB_BACKEND defaults to "memory"
```

Open http://127.0.0.1:8000 — a live Dublin map with gradient pins and urgency pulsing.

## Quickstart (Postgres)

```bash
createdb raddar                                  # or use docker-compose (below)
export DB_BACKEND=postgres
export DATABASE_URL="postgresql+asyncpg://localhost:5432/raddar"
python -m scripts.seed_db                         # create tables + load Dublin seed events
uvicorn app.main:app --reload
```

Tables (`events`, `users`, `bookmarks`) are auto-created on startup. Or run the whole stack
(Postgres + app) with **`docker compose up`**.

## Database

- **Async SQLAlchemy 2.0 + asyncpg.** Engine/session in [`app/db/base.py`](app/db/base.py),
  ORM models in [`app/db/orm.py`](app/db/orm.py), repositories in
  [`app/db/postgres.py`](app/db/postgres.py).
- **Backend selection** is per-request in [`app/db/deps.py`](app/db/deps.py) — events, users,
  and bookmarks all swap between Postgres and the in-memory store via one switch (`DB_BACKEND`).
- Hosted `postgres://`/`postgresql://` URLs are auto-normalized to the asyncpg driver
  (`Settings.sqlalchemy_url`), so Render/Heroku connection strings work as-is.

### Migrations (Alembic)

```bash
alembic upgrade head                       # apply migrations
alembic revision --autogenerate -m "msg"   # create a migration after model changes
alembic downgrade -1                        # roll back one
```

The URL comes from `DATABASE_URL` (via app settings) — no duplication in `alembic.ini`.
In **dev**, `AUTO_CREATE_TABLES=true` (default) also runs `create_all` on startup for
convenience. In **production**, set `AUTO_CREATE_TABLES=false` and let `alembic upgrade head`
own the schema (the `render.yaml` `preDeployCommand` does this automatically). For a DB that
already has tables, `alembic stamp head` once to adopt it.

## Routes

| Route | Purpose |
|---|---|
| `GET /` | Map page (server-rendered first paint + MapLibre) |
| `GET /api/events?lat&lng` | JSON read-API: Now-and-Next (3h) + 1-mile geofence |
| `GET /event/{id}` | Indexable event page (JSON-LD); 410 if expired |
| `GET /dublin` | "Events in Dublin tonight" SEO landing page |
| `GET /sitemap.xml`, `/robots.txt` | SEO surfaces (current events only) |
| `GET /api/session` | Auth state + CSRF token |
| `GET /api/events`, `POST /api/events` | Read (discovery) + **host a user event** (auth + CSRF; pins at your location) |
| `GET/POST/DELETE /api/bookmarks` | Bookmark API (Lazy Wall: 401 + login_url when anonymous) |
| `GET /auth/login`, `/auth/callback`, `POST /auth/logout` | OAuth flow (mock provider by default) |
| `GET /healthz` | Liveness probe |

## Ingestion pipeline

Populates Postgres with events: **fetch (concurrent) → normalize → dedup → upsert → purge**.

```bash
DB_BACKEND=postgres python -m app.pipeline.run            # run
DB_BACKEND=postgres python -m app.pipeline.run --dry-run  # normalize only, no writes
```

- **Normalization** ([`app/pipeline/normalize.py`](app/pipeline/normalize.py)): maps category/cost
  synonyms, parses times to UTC, fills a per-category default duration, geocodes address-only
  records, and **rejects** anything outside the Dublin bbox or with a bad category (dead-lettered to the log).
- **Dedup**: `event_id` is a hash of `(title, start_time, lat, lng)`, so the same event from
  different sources collapses into one row — and re-runs **upsert** (idempotent, never duplicates).
- **Self-cleaning**: `purge_expired` deletes rows past `expires_at` each run.
- **Failure isolation**: one source erroring doesn't sink the run; it's logged and others proceed.
- **Sources** ([`app/pipeline/sources.py`](app/pipeline/sources.py)): `FixtureSource` (bundled Dublin
  sample, runs with no credentials) + `PredictHQSource`/`EventbriteSource` stubs to fill in.

Each run logs `{fetched, inserted, updated, skipped_duplicate, rejected, purged, duration_seconds}`.

### Real sources

`build_sources()` enables real sources when their credentials are present, else falls back to
the bundled Dublin fixture:

- **Eventbrite** (`EVENTBRITE_TOKEN` + `EVENTBRITE_ORGANIZATION_ID`) — complete client (auth,
  pagination, retry/backoff via [`app/pipeline/http.py`](app/pipeline/http.py), online-event
  filtering, venue→coords). *Note: Eventbrite's API is org-scoped — it only returns events your
  own account organizes, not city-wide public events.*
- **Tier-2 scraping** (`FIRECRAWL_API_KEY`) — [`app/pipeline/scrapers.py`](app/pipeline/scrapers.py)
  extracts structured events from Dublin listings sites (configured in
  [`fixtures/scrape_targets.json`](app/pipeline/fixtures/scrape_targets.json)) via Firecrawl.
  Scraped events have addresses, not coordinates, so set **`GOOGLE_GEOCODING_KEY`** too — without
  it, address-only events are rejected.
- **PredictHQ** (`PREDICTHQ_TOKEN`) — stub to fill in the same way (best city-wide breadth).

### Scheduling

```bash
# Option A — Render cron (in render.yaml): runs `python -m app.pipeline.run` every 10 min.
# Option B — system crontab:
*/10 * * * * cd /app && DB_BACKEND=postgres /app/.venv/bin/python -m app.pipeline.run
# Option C — in-process loop (long-running host, no external cron):
DB_BACKEND=postgres python -m app.pipeline.schedule   # every PIPELINE_INTERVAL_SECONDS
```

## Lazy Wall (auth)

Browse fully anonymously. The first high-intent action (bookmark) returns `401` with a
`login_url`; the client sends the user to single-tap OAuth and back. Runs on a **mock
provider** out of the box (no credentials) — set `OAUTH_MOCK=false` and add
`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` to go live. Sessions are signed HttpOnly cookies;
mutations require a CSRF token (`/api/session` → `X-CSRF-Token` header).

## Deploy

`Dockerfile` + `render.yaml` included. Set `COOKIE_SECURE=true`, a real `SESSION_SECRET`,
Airtable creds, and (when ready) OAuth creds. Honors `$PORT`.

## Architecture (the key boundary)

- **Jinja (server)** → HTML shell, SEO meta/JSON-LD, initial event data embedded for instant paint.
- **MapLibre + JS (client)** → live interactive map, browser geolocation, gradient pins, urgency pulsing, live re-fetch.

All filtering (`Now-and-Next` + 1-mile geofence) lives in [`app/core/`](app/core/) and is shared
by the page routes and the API — the mobile app can consume the same `/api/events` later.

## Layout

```
app/
  main.py            FastAPI entrypoint (+ lifespan: create tables on startup)
  config.py          settings + Dublin constants + DATABASE_URL
  models.py          canonical Event schema (shared with pipeline)
  core/
    geo.py           haversine + 1-mile geofence
    temporal.py      Now-and-Next window
    service.py       discover() — combines both, used everywhere
  db/
    base.py          async SQLAlchemy engine, session, get_session dep
    orm.py           ORM models: events, users, bookmarks
    postgres.py      Postgres repositories (events, users, bookmarks)
    repository.py    InMemory (seeded) + Airtable backends (events)
    users.py         User model + in-memory stores + store protocols
    deps.py          per-request backend selection (postgres | memory | airtable)
  auth/              OAuth providers, login/callback routes, session/CSRF deps
  api/               events, session, bookmarks JSON endpoints
  web/routes.py      Jinja pages + sitemap/robots
  templates/         base, map, event_detail, city, mock_consent
scripts/seed_db.py   create tables + load Dublin seed events into Postgres
static/               js (map/pins/urgency/bookmark), css, sw.js, manifest
tests/                discovery, airtable, auth, hardening, postgres
```

## Tests

```bash
pytest                 # postgres tests auto-skip if no DB reachable
# point the integration tests at a throwaway DB:
TEST_DATABASE_URL=postgresql+asyncpg://localhost/raddar_test pytest
```

## Going to production

1. **DB:** `DB_BACKEND=postgres` + `DATABASE_URL`. Tables auto-create on startup; add Alembic for real migrations. (Airtable remains a supported read-only events source via `DB_BACKEND=airtable`.)
2. **Map:** swap the OSM raster style in `map.js` for a vector style if desired.
3. **Auth:** set `OAUTH_MOCK=false` + Google/Apple credentials; set `COOKIE_SECURE=true` and a real `SESSION_SECRET`.
