"""Server-rendered (Jinja) routes.

These pages are the SEO surface: the home/map page embeds initial events for instant first
paint, and event/city pages are indexable. The interactive map itself is client JS (MapLibre).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.auth.deps import current_user
from app.config import Settings, get_settings
from app.core.service import discover, get_event
from app.db.deps import get_bookmark_store, get_event_repo
from app.db.repository import EventRepository
from app.db.users import BookmarkStore, User
from app.models import EventOut

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> HTMLResponse:
    # Initial paint uses the Dublin anchor; the client refines once geolocation resolves.
    events = await discover(repo, settings, lat=settings.anchor_lat, lng=settings.anchor_lng)
    return templates.TemplateResponse(
        request,
        "map.html",
        {
            "settings": settings,
            "events": events,
            # embedded JSON → no loading spinner on first paint
            "events_json": json.dumps([e.model_dump(mode="json") for e in events]),
        },
    )


@router.get("/event/{event_id}", response_class=HTMLResponse)
async def event_detail(
    request: Request,
    event_id: str,
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> Response:
    event = await get_event(repo, event_id)
    if event is None:
        # Don't index stale/expired content.
        return PlainTextResponse("Event not found or no longer happening.", status_code=410)
    return templates.TemplateResponse(
        request, "event_detail.html", {"settings": settings, "event": event}
    )


@router.get("/dublin", response_class=HTMLResponse)
async def city_page(
    request: Request,
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> HTMLResponse:
    events = await discover(repo, settings, lat=settings.anchor_lat, lng=settings.anchor_lng)
    # cluster by category for the SEO landing page (soonest-ending order preserved within each)
    clusters: dict[str, list] = {}
    for e in events:
        clusters.setdefault(e.category.value, []).append(e)
    return templates.TemplateResponse(
        request,
        "city.html",
        {"settings": settings, "events": events, "clusters": clusters},
    )


@router.get("/me", response_class=HTMLResponse)
async def my_raddar(
    request: Request,
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
    user: User | None = Depends(current_user),
    bookmarks: BookmarkStore = Depends(get_bookmark_store),
) -> Response:
    """Authenticated 'Your Raddar' page: saved events + the pins you're hosting.

    A page (not an API), so an anonymous visitor is sent through the Lazy Wall rather than
    getting a raw 401.
    """
    if user is None:
        return RedirectResponse(url="/auth/login?next=/me", status_code=303)

    # Saved events: resolve each bookmark to a still-active event (expired ones drop off).
    saved: list[EventOut] = []
    for event_id in await bookmarks.list(user.id):
        event = await get_event(repo, event_id)
        if event is not None:
            saved.append(EventOut.from_event(event, urgency_minutes=settings.urgency_minutes))
    saved.sort(key=lambda o: o.minutes_until_end)

    hosted = [
        EventOut.from_event(e, urgency_minutes=settings.urgency_minutes)
        for e in await repo.list_by_user(user.id)
    ]
    return templates.TemplateResponse(
        request,
        "me.html",
        {"settings": settings, "user": user, "saved": saved, "hosted": hosted},
    )


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots(request: Request) -> PlainTextResponse:
    base = str(request.base_url).rstrip("/")
    return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n")


@router.get("/sitemap.xml")
async def sitemap(
    request: Request,
    settings: Settings = Depends(get_settings),
    repo: EventRepository = Depends(get_event_repo),
) -> Response:
    base = str(request.base_url).rstrip("/")
    events = await discover(repo, settings, lat=settings.anchor_lat, lng=settings.anchor_lng)
    urls = [f"{base}/", f"{base}/dublin"]
    urls += [f"{base}/event/{e.event_id}" for e in events]  # current events only
    body = "\n".join(f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}\n</urlset>\n"
    )
    return Response(content=xml, media_type="application/xml")
