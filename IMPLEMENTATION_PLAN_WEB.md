# Raddar — Web Version Implementation Plan

> The web companion to the Raddar mobile app — same product, same data, browser-native.
> *"The zero-search map that shows you exactly what's happening within a 15-minute walk, starting right now."*

**Status:** Pre-development
**Companion to:** `IMPLEMENTATION_PLAN.md` (mobile / FlutterFlow)
**Launch city:** Dublin, Ireland (see mobile plan §0.1)
**Last updated:** 2026-06-26

---

## 0. Stack Decision — Python + Jinja (Confirmed)

The web version is a **Python-first server-rendered app** that reuses the entire backend already planned for mobile.

| Layer | Choice | Why |
|---|---|---|
| **Web server** | **FastAPI** | Async, matches the pipeline's `httpx`/`asyncio` patterns; serves both Jinja pages *and* a JSON read-API the mobile app can later share |
| **Templating** | **Jinja2** | Server-rendered HTML → strong SEO; lightweight; pure Python control flow |
| **Map (client)** | **MapLibre GL JS** | Free/open-source (no per-load fees), vector tiles, smooth styling that supports the Vibe-First gradient pins. *Fallback: Leaflet (simpler, raster).* |
| **Geolocation** | Browser **Geolocation API** | Standard, permission-gated |
| **Interactivity** | Vanilla JS or **Alpine.js / htmx** | Urgency timers, pulsing animations, live re-fetch — keep JS minimal |
| **Styling** | Tailwind CSS (or plain CSS) | Fast iteration, consistent with pin gradient system |
| **Data / DB** | **PostgreSQL** (async SQLAlchemy + asyncpg) + canonical schema | Operational DB shared with the pipeline/mobile — see mobile plan §2. (Airtable retained as a legacy read-only events source.) |
| **Pipeline** | **Shared** — the 3-tier Python ingestion already feeds both | No changes needed |
| **Hosting** | Render / Fly.io / Railway (container) | Native Python hosting; cron alongside web |

### The critical architectural boundary
```
Jinja renders (server)              MapLibre + JS handles (client)
─────────────────────              ──────────────────────────────
• HTML shell / page layout         • The live interactive map
• SEO meta tags, OpenGraph         • Browser geolocation → geofence
• Initial event list (embedded     • 1-mile distance filtering
  JSON for first paint, no spinner)• Custom gradient pins
• Event detail pages (indexable)   • Urgency pulsing (≤30 min timer)
• City landing pages               • Live re-fetch from /api/events
```
**Rule:** Jinja gives fast, indexable first paint; JS makes it a real-time map. Never try to render the interactive map in Jinja, and never block first paint waiting on JS.

---

## 1. What's Shared vs. New

| Component | Status |
|---|---|
| 3-tier data pipeline (PredictHQ/Eventbrite/Places, scraping, editorial) | ♻️ **Reused as-is** |
| Canonical event schema + `pydantic` models | ♻️ **Reused as-is** |
| PostgreSQL operational DB (schema via Alembic) | ♻️ **Shared** — pipeline writes, web + mobile read |
| Dublin config (timezone, bounding box, scraping targets) | ♻️ **Reused as-is** |
| Self-cleaning / `is_today` / 3-hour window logic | ♻️ **Reused as-is** |
| FastAPI read-API (`/api/events`) | 🆕 **New** (also future-usable by mobile) |
| Jinja templates + server routes | 🆕 **New** |
| MapLibre map + client JS (geofence, pins, urgency) | 🆕 **New** |
| SEO surfaces (event/city pages, sitemaps) | 🆕 **New — web-only opportunity** |
| PWA (installable, optional push) | 🆕 **New** |

---

## 2. Web-Specific Product Considerations

The same five product rules apply (Now-and-Next, Geofenced Bubble, Vibe-First, Zero-Friction, Lazy Wall), with web realities:

| Rule | Web nuance |
|---|---|
| **Zero-Friction (TTV ≤ 5s)** | No app install. First paint must be instant via Jinja-embedded initial data; ask for geolocation immediately with clear copy. |
| **Geofenced Bubble** | Browser Geolocation is less precise and permission-gated. **Fallback:** if denied, default to Dublin city-centre anchor (`53.3498, -6.2603`) so the map is never empty. |
| **Vibe-First** | Same gradient pins, rendered as MapLibre symbol/circle layers driven by `category` → gradient. |
| **Now-and-Next** | Enforced server-side in `/api/events` (3-hour window + 1-mile box), identical logic to mobile. |
| **Lazy Wall** | Anonymous browsing; OAuth (Apple/Google) only on bookmark/host. Web adds session-cookie handling. |
| **SEO (web-only)** | Mobile is "zero-search"; web *embraces* search as a top-of-funnel channel — indexable event and city pages drive discovery. **Strategic addition, not a contradiction.** |

---

## 3. Application Structure

```
raddar-web/
├── app/
│   ├── main.py                 # FastAPI app, route registration
│   ├── config.py               # Dublin config, env, settings (pydantic-settings)
│   ├── api/
│   │   └── events.py           # GET /api/events?lat&lng (3hr + 1mi filter) → JSON
│   ├── web/
│   │   ├── routes.py           # GET / (map), /event/{id}, /dublin (city page)
│   │   └── seo.py              # sitemap.xml, robots.txt, structured data
│   ├── db/
│   │   ├── base.py / orm.py    # async SQLAlchemy engine + ORM models
│   │   ├── postgres.py         # Postgres repositories (events/users/bookmarks)
│   │   └── repository.py       # in-memory + Airtable (legacy) event sources
│   ├── models.py               # ♻️ shared canonical Event model (from pipeline)
│   └── templates/              # Jinja2
│       ├── base.html           # shell, meta, OpenGraph
│       ├── map.html            # home/map page (embeds initial events JSON)
│       ├── event_detail.html   # indexable per-event page
│       └── city.html           # "Events in Dublin tonight" landing page
├── static/
│   ├── js/
│   │   ├── map.js              # MapLibre init, geolocation, geofence
│   │   ├── pins.js             # category→gradient, pin rendering
│   │   └── urgency.js          # ≤30min pulsing timer, live re-fetch
│   └── css/
├── tests/
└── pyproject.toml              # FastAPI, jinja2, httpx, pydantic, uvicorn
```

---

## 4. Phased Roadmap (assumes pipeline + schema from mobile plan already exist)

### Phase W0 — Web Foundations (Week 1)
- [ ] Scaffold FastAPI + Jinja2 + uvicorn project; reuse `Event` pydantic model
- [x] Postgres read layer (async SQLAlchemy) shared with the pipeline; in-memory + Airtable fallbacks
- [ ] Base Jinja template (`base.html`) with SEO meta scaffolding
- [ ] Pick MapLibre tile source (free style or self-hosted) biased to Dublin
- [ ] Local dev: `uvicorn app.main:app --reload`

**Exit:** `/` serves a server-rendered page; a hardcoded event lists via Jinja.

### Phase W1 — Read API + Map Core (Weeks 2–3)
- [ ] `GET /api/events?lat&lng` → enforces 3-hour Now-and-Next window + 1-mile box, returns JSON
- [ ] `map.html` embeds initial Dublin-centre events as JSON for instant first paint (no spinner)
- [ ] `map.js`: MapLibre init, request browser geolocation, fallback to Dublin anchor on deny
- [ ] Client-side 1-mile distance filter from resolved location
- [ ] `pins.js`: category → gradient mapping (`Music → red`, `Food → green`, EUR cost encoded)

**Exit:** Open the site in Dublin → map renders real, color-coded, in-window events within 5s.

### Phase W2 — Urgency System + States (Weeks 3–4) · `/spe-uiux` ✅
- [x] `urgency.js`: recurring timer; pulsing border/glow on pins ending ≤30 min
- [x] Periodic live re-fetch from `/api/events` (90s)
- [x] UI states: loading skeleton, live, **constructive empty state** (no events → time estimate, not blank), stale/reconnecting banner
- [x] Responsive layout: mobile-web bottom sheet + desktop split (map + list)

**Exit:** Urgency pulsing works; map self-updates; empty/loading states are graceful on phone and desktop.

### Phase W3 — SEO Surfaces (Weeks 4–5) · web-only advantage ✅
- [x] `event_detail.html`: server-rendered, indexable per-event page with JSON-LD `Event` structured data
- [x] `city.html`: "Events in Dublin tonight" landing page with category clusters
- [x] `sitemap.xml` (dynamic, current events only), `robots.txt`, canonical URLs, OpenGraph + Twitter cards
- [x] Expired events return 410 (don't index stale content)

**Exit:** A Google search like "live music Dublin tonight" can surface a Raddar page; shared links preview richly.

### Phase W4 — Lazy Wall + Accounts (Weeks 5–6) · both ✅ (mock OAuth)
- [x] Fully anonymous browsing (no auth to view map/details)
- [x] OAuth triggered only on bookmark/host — **mock provider working**; Google/Apple are drop-in stubs (add creds + set `OAUTH_MOCK=false`)
- [x] Server-side signed-cookie sessions (Starlette `SessionMiddleware`); bookmark persistence via user repo (→ shared user table in prod)
- [x] CSRF protection on mutations (double-submit token); HttpOnly/SameSite=Lax/secure cookies
- [ ] Wire real Google/Apple credentials (needs provider OAuth apps)

**Exit:** Browse anonymously → bookmark triggers single-tap OAuth → bookmarks persist. ✅

### Phase W5 — PWA + Hardening + Launch (Weeks 6–8) ✅ (deploy pending)
- [x] PWA manifest + service worker (installable; network-first pages/API, cache-first assets)
- [ ] Optional Web Push for saved-event reminders (deferred, like mobile)
- [x] Accessibility: ARIA labels on map/list (keyboard nav + contrast audit ongoing)
- [x] Security headers (CSP, X-Frame-Options, nosniff, Referrer/Permissions-Policy, HSTS in prod); rate-limit `/api/*`
- [x] Deploy config: `Dockerfile` + `render.yaml` (managed Postgres + `alembic upgrade head` preDeploy + OAuth env wiring)
- [ ] Lighthouse pass; deploy to Render/Fly.io with pipeline cron; closed Dublin beta

**Exit:** Public web MVP live for Dublin, Lighthouse-healthy, indexed, no data-quality incidents in a 1-week beta.

---

## 5. Web-Specific Risks

| Risk | Mitigation |
|---|---|
| Browser geolocation denied/inaccurate | Fallback to Dublin city-centre anchor; never show a blank map |
| Flutter-style "app feel" expectations on web | Keep JS lean (Alpine/htmx), prioritize speed over heavy SPA framework |
| SEO indexing stale/expired events | Dynamic sitemap of current events only; 410 on expired; `is_today` drives visibility |
| MapLibre tile costs/limits if using a hosted provider | Use free MapLibre styles or self-host tiles; cache aggressively |
| Duplicated logic drifting from mobile | Centralize Now-and-Next + 1-mile filtering in shared Python; both clients call the same API |
| Map performance with many pins | Cluster pins at zoom-out; only render in-viewport + in-window events |

---

## 6. Definition of Done (Web MVP)

1. Open the site in Dublin → live, accurate, color-coded map in **≤ 5 seconds** (Jinja-embedded first paint).
2. Pins are gradient-coded by category, encode EUR cost, and **pulse when an event ends in ≤30 min**.
3. Only events **active now or within 3 hours**, within **1 mile** (or Dublin anchor fallback), appear.
4. **Fully anonymous**; OAuth only on bookmark/host.
5. Event and city pages are **server-rendered and indexable**; expired events are not indexed.
6. Backend pipeline, schema, and DB are **100% shared** with mobile — no duplication.

---

## 7. Why this stack fits Raddar

- **One language, one team** — the same Python skills that build the pipeline build the web app; the `/spe-python` persona owns server + API, `/spe-uiux` owns map/UX.
- **Shared read-API** — `/api/events` built here can later serve the FlutterFlow mobile app, collapsing two data layers into one.
- **SEO as growth** — server-rendered Jinja turns the web version into an acquisition funnel the mobile app structurally can't be.
- **Lean** — FastAPI + Jinja + MapLibre is far lighter than a full React SPA, matching the "speed over richness" product principle.

> Use `/spe-python` for FastAPI, the read-API, and server logic. Use `/spe-uiux` for the MapLibre map, pin/urgency visuals, and responsive layout.
