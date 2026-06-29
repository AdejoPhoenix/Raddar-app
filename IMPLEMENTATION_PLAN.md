# Raddar — Detailed Implementation Plan

> Hyper-local, spontaneous event discovery platform.
> *"The zero-search map that shows you exactly what's happening within a 15-minute walk, starting right now."*

**Status:** Pre-development (blueprint approved, no code yet)
**Source of truth:** `Radar_App_Product_Strategy_Blueprint.pdf`
**Last updated:** 2026-06-26

---

## 0. Assumptions & Open Decisions

These shape scope. Confirm before Phase 1 — defaults are chosen for a lean MVP.

| Decision | Default Assumption | Impact if changed |
|---|---|---|
| **Launch city** | **Dublin, Ireland** (confirmed) — see Section 0.1 | Determines scraping targets, API quotas, geocoding volume |
| **Team** | 1–2 builders (low-code + Python) | Affects parallelism of frontend/backend tracks |
| **Operational DB** | **PostgreSQL** (confirmed) — shared with the web app | Schema owned by Alembic migrations in `raddar-web`; the pipeline writes into the same DB the web (and future mobile) reads |
| **Timeline** | ~10–12 weeks to public MVP | Compresses/expands per phase |
| **Budget posture** | Free/low tiers of all APIs for MVP | PredictHQ/Google Places have real costs at volume |

### 0.1 Launch City Configuration — Dublin, Ireland

Dublin is a strong launch choice: compact, dense urban core; high concentration of pubs, live music, food markets, and pop-ups; walkable; strong tourism + events ecosystem feeding all three data tiers.

| Parameter | Value |
|---|---|
| **Timezone** | `Europe/Dublin` (UTC+0 winter / UTC+1 summer IST) — DST-aware. Store UTC, convert on display. |
| **City-center anchor** | ~`53.3498, -6.2603` (O'Connell Bridge / Trinity College) |
| **Pipeline bounding box** (ingest filter) | lat `53.30`–`53.41`, lng `-6.40`–`-6.10` (covers core + inner suburbs) |
| **Reject-if-outside** | Geocoded coords outside the bounding box are rejected (catches geocoding errors) |
| **Display geofence** | Strict 1.0-mile radius from device GPS (per product rule) — independent of ingest box |
| **Currency / cost tiers** | EUR — `Free`, `€`, `€€`, `€€€` |

**Tier 2 scraping targets (Dublin-specific):**
- *Alternative news / listings:* District Magazine, Lovin Dublin, Totally Dublin, Dublin Live, TheJournal events, Dublin Event Guide
- *Brewery / pub calendars:* Guinness Open Gate Brewery, Rascals Brewing, Trouble Brewing, The Cobblestone (trad sessions), Whelan's, Vicar Street listings
- *Markets / pop-ups:* Eatyard, Honest2Goodness Market, Dublin Flea Market, Temple Bar Food Market
- *Municipal / tourism:* visitdublin.com, Dublin.ie events, Dublin City Council culture/events, Fáilte Ireland

**Tier 1 API notes for Dublin:**
- PredictHQ + Eventbrite both have solid Dublin coverage; filter Eventbrite hard for in-person only (drop webinars/online)
- Google Places/Geocoding: bias all queries to the Dublin bounding box to reduce ambiguous matches (e.g., "Dublin, Ohio")
- Quota note: Ireland is a single-country, single-city scope — free/low tiers should suffice for MVP volume

**DST caution:** `Europe/Dublin` observes DST. The `is_today` refresh cron and the "starting within 3 hours" window must compute against local Dublin wall-clock time, then store/compare in UTC — do not hardcode a fixed UTC offset.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│  DATA SEEDING PIPELINE (Python + Make.com)                   │
│                                                               │
│  Tier 1: Enterprise APIs    Tier 2: Scraping   Tier 3: Manual │
│  PredictHQ / Eventbrite /   Browse AI /         Editorial     │
│  Google Places              Firecrawl           curation      │
│         │                       │                   │         │
│         └───────────┬───────────┴───────────────────┘         │
│                     ▼                                          │
│         Python normalization layer                            │
│         (pydantic validation → dedup → geocode → temporal tag)│
│                     │                                          │
│                     ▼                                          │
│         Canonical Event Schema                                │
└─────────────────────┬───────────────────────────────────────┘
                      ▼
         ┌────────────────────────┐
         │  PostgreSQL             │  ← operational DB (shared)
         │  (self-cleaning, is_today│     schema via Alembic (raddar-web)
         │   flag, expires_at)     │
         └───────────┬─────────────┘
                     ▼ FastAPI read-API (/api/events)
         ┌───────────────────────────────────────┐
         │  Clients                               │
         │  • Web (FastAPI + Jinja + MapLibre)    │
         │  • FlutterFlow Mobile App              │
         │    - Map view (1mi geofence)           │
         │    - Custom pins / urgency animations  │
         │    - Lazy Wall OAuth                    │
         └───────────────────────────────────────┘
```
> **Note:** Postgres replaced the original Airtable/Baserow choice once the web app was built
> on it. The pipeline writes events into Postgres; both web and mobile read via the shared
> FastAPI `/api/events`. Make.com remains optional for simple linear automations.

**Two parallel tracks** (owned by the two project personas):
- **Backend / Data** → `/spe-python`
- **Frontend / UX** → `/spe-uiux`

---

## 2. Canonical Event Schema

The single contract between backend and frontend. Define this first — everything else normalizes into it.

| Field | Type | Notes |
|---|---|---|
| `event_id` | string (UUID) | Stable, generated at ingest |
| `title` | string | Display name |
| `title_normalized` | string | Lowercased, trimmed — for dedup |
| `category` | enum | `Music`, `Food`, `Market`, `Art`, `Nightlife`, `Sports`, `Community` |
| `start_time` | datetime (UTC, ISO 8601) | Always timezone-aware |
| `end_time` | datetime (UTC, ISO 8601) | Fallback: `start_time + default_duration` per category |
| `lat` | float | Required — never store unresolved |
| `lng` | float | Required — never store unresolved |
| `cost_tier` | enum | `Free`, `€`, `€€`, `€€€` (EUR — Dublin) |
| `source_tier` | enum | `1_api`, `2_scrape`, `3_editorial` |
| `source_name` | string | e.g. `eventbrite`, `firecrawl:brewery_x` |
| `is_today` | boolean | Computed server-side, refreshed by cron |
| `created_at` | datetime (UTC) | |
| `expires_at` | datetime (UTC) | Drives self-cleaning purge |

**Dedup key:** `(title_normalized, start_time, round(lat,4), round(lng,4))`

---

## 3. Phased Roadmap

### Phase 0 — Foundations (Week 1)
**Goal:** Tooling, accounts, schema locked.

- [ ] Provision accounts: FlutterFlow, Google Cloud (Maps/Places/Geocoding), PredictHQ, Eventbrite, Firecrawl/Browse AI, Postgres host (Render/Fly) — Make.com optional
- [x] ~~Create DB with canonical schema~~ → **Postgres schema exists**, managed by Alembic in `raddar-web` (`events`/`users`/`bookmarks`). Add indexes on `lat/lng`, `start_time`, `expires_at` via a migration. The pipeline writes into this DB.
- [ ] Set up Python repo: `pyproject.toml`, `pydantic` v2, `httpx`, `loguru`, `python-dotenv`, `pytest`
- [ ] Secrets management: `.env` for local, secret store for production cron
- [ ] Define and version the canonical schema as `pydantic` models (`Event`, `RawSourceEvent`)
- [x] ~~Pick launch city~~ → **Dublin** confirmed; bounding box + timezone documented (Section 0.1)
- [ ] Configure Google Places/Geocoding to bias queries to the Dublin bounding box

**Exit criteria:** Empty pipeline runs end-to-end with one hardcoded test event written to the DB.

---

### Phase 1 — Backend Data Pipeline (Weeks 2–4) · `/spe-python`
**Goal:** The map has real, fresh, accurate data to render.
**Status:** Pipeline framework built in `raddar-web/app/pipeline/` (fetch→normalize→dedup→upsert→purge), runs end-to-end against Postgres, idempotent, tested. Real Tier-1/2 source clients remain to be wired (credentials).

**1a. Tier 1 — Enterprise APIs**
- [x] Eventbrite client: real (auth, pagination, retry/backoff, online-event filtering, venue→coords) — tested via `httpx.MockTransport`; needs a token to go live
- [x] Shared retry helper with exponential backoff + jitter on 429/5xx (`pipeline/http.py`)
- [ ] PredictHQ client *(stub: `sources.PredictHQSource`)*
- [ ] Google Places client: venue + ephemeral place data
- [x] Concurrent fetch across sources with `asyncio.gather` + failure isolation
- [x] Normalize all sources into `Event`; reject malformed records to dead-letter log

**1b. Coordinate enrichment**
- [x] Geocoder interface + address→coords fallback (`FixtureGeocoder`; `GoogleGeocoder` stub, Dublin-bbox biased)
- [ ] Cache resolved venue coordinates (stable data) — never cache event times

**1c. Deduplication + temporal tagging**
- [x] Cross-source dedup via deterministic `event_id` = hash(title, start, lat, lng)
- [x] `expires_at` set; `is_today` computed in the model; 3-hour window enforced at query time (web `discover()`)
- [x] Idempotent — re-runs upsert, never duplicate (verified: run 2 = 0 inserted / N updated)

**1d. Self-cleaning**
- [x] `purge_expired` deletes rows past `expires_at` each run
- [x] Run logging: fetched / inserted / updated / skipped / rejected / purged / duration
- [x] Scheduling: Render cron service + crontab line + in-process loop (`pipeline/schedule.py`)
- [x] `--dry-run` flag (normalize without writing)

**1e. Tier 2 — Scraping**
- [x] Untrusted input handled via `pydantic` `RawEvent` validation at the boundary
- [ ] Firecrawl/Browse AI routines (alt-news, brewery calendars, tourism boards) → `RawEvent`
- [ ] Schedule off-peak (02:00–05:00 local)

**1f. Tier 3 — Editorial**
- [x] Validation path shared — editorial records go through the same `normalize()` (can't bypass schema rules)
- [ ] Lightweight admin/form for hand-curated entries (or seed-style script)

**Exit criteria:** DB stays populated with valid, deduplicated, geographically accurate events for the launch city, auto-cleaning expired ones, with no manual intervention for 48h. *(Met for the framework + fixtures; needs real source clients for live data.)*

---

### Phase 2 — Frontend Core: The Map (Weeks 3–6, overlaps Phase 1) · `/spe-uiux`
**Goal:** Open app → see live events on a map within 5 seconds.

**2a. Onboarding (Zero-Friction Funnel — TTV ≤ 5s)**
- [ ] Hardware Permission Gate (sec 0–3): location request with clear, trust-building micro-copy
- [ ] No splash overlays, no feature cards, no instructional screens
- [ ] Notification permission explicitly deferred

**2b. Map interface**
- [ ] Map renders immediately on local neighborhood (FlutterFlow map widget)
- [ ] Client-side distance module: strict 1.0-mile display filter from device GPS
- [ ] Bind DB query to geofence + Now-and-Next 3-hour window

**2c. Custom pin component system** (single parameterized widget, not variants)
- [ ] Categorical color mutation: `category` string → gradient (`Music → Gradient_Red`, `Food → Gradient_Green`, …)
- [ ] Cost + category encoded visually (Vibe-First — no text)
- [ ] Pin tap → lightweight event detail sheet

**2d. Urgency Visual System** (Raddar's primary engagement hook)
- [ ] Recurring client-side timer evaluating distance + time-remaining
- [ ] Pulsing border animation when event ends in ≤30 min

**2e. UI states**
- [ ] Loading skeleton, live state, **constructive empty state** (geofence with no events → time estimate, not blank map), stale state

**Exit criteria:** A user in the launch city opens the app and sees accurate, color-coded, time-relevant pins within 5 seconds, with urgency pulsing working.

---

### Phase 3 — The Lazy Wall & High-Intent Actions (Weeks 6–8) · both
**Goal:** Anonymous until intent; then single-tap auth.

- [ ] App fully functional anonymously (browse, view detail)
- [ ] OAuth trigger only on high-intent mutations: bookmark, book, host-register
- [ ] Apple ID + Google single-tap OAuth
- [ ] Post-auth: bookmarks persistence, basic user record
- [ ] Backend: user table, auth token handling, bookmark association

**Exit criteria:** A user can browse fully anonymously, then bookmark an event — at which moment (and only then) they hit single-tap OAuth.

---

### Phase 4 — Hardening & Launch Prep (Weeks 8–10)
**Goal:** Reliable, observable, store-ready.

- [ ] Backend: monitoring/alerting on pipeline failures, dead-letter review process, `--dry-run` validated
- [ ] Load test: simulate live-traffic + scraping collision windows
- [ ] Frontend: performance pass (map render < target, animation jank-free), error/offline states
- [ ] Offline-first behavior (cache last geofence result)
- [ ] App Store / Play Store assets, privacy disclosures (location usage), TestFlight/internal track
- [ ] Beta with small group in launch city

**Exit criteria:** Closed beta runs for 1 week with no data-quality incidents and acceptable performance.

---

### Phase 5 — Public MVP Launch (Weeks 10–12)
- [ ] Production cron schedule for all 3 tiers live
- [ ] Public release in launch city
- [ ] Instrument core funnel: app-open → map-render → pin-tap → bookmark/book
- [ ] Establish data-quality dashboard (phantom events, empty-map rate, stale-event rate)

---

## 4. Cross-Cutting Concerns

| Concern | Standard |
|---|---|
| **Time zones** | Store UTC everywhere; convert at display only. Never store tz-naive datetimes. |
| **Coordinates** | Always validated; a wrong lat/lng breaks the core "15-min walk" promise. |
| **Idempotency** | Every pipeline job re-runnable without duplicating data. |
| **Failure isolation** | One ingestion tier failing must not block the other two. |
| **Secrets** | Never hardcoded; `python-dotenv` local, secret store in prod. |
| **Privacy** | Location copy must feel helpful, not surveilling; data minimization. |
| **Observability** | Structured logging per pipeline run; funnel analytics on frontend. |

---

## 5. Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cold-start: sparse data → empty maps | High | All 3 tiers live before launch; constructive empty state; pick dense launch city |
| API costs spike (Places/PredictHQ) | Medium | Cache stable data; quota alerts; budget caps |
| Scraped data quality/legality | Medium | Validate at boundary; respect robots/ToS; dead-letter bad records |
| FlutterFlow hits a wall on custom map logic | Medium | Drop to custom Dart for distance/timer/animation; isolate as code actions |
| Stale events erode trust | High | Self-cleaning cron; `is_today` refresh; 3-hour window enforced at query |
| Geocoding errors place events wrong | Medium | Validate resolved coords against city bounding box; reject out-of-bounds |

---

## 6. Definition of Done (MVP)

1. A first-time user in the launch city goes from app-open to a live, accurate map in **≤ 5 seconds**.
2. Pins are **color-coded by category**, encode cost, and **pulse when an event ends in ≤30 min**.
3. Only events **active now or starting within 3 hours**, within **1 mile**, appear.
4. The app is **fully usable anonymously**; OAuth appears **only** on bookmark/book/host.
5. The pipeline keeps the DB **fresh and self-cleaning** with no manual intervention.
6. No stale, duplicate, or geographically-wrong events reach the map.

---

## 7. Suggested Working Cadence

- Use `/spe-python` when designing/reviewing any pipeline, API integration, schema, or Python code.
- Use `/spe-uiux` when designing/reviewing any screen, map component, animation, or onboarding flow.
- Backend (Phase 1) and Frontend (Phase 2) run in parallel against the **frozen canonical schema** (Section 2) — freeze it early to enable parallelism.
