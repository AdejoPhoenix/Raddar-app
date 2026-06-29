"""OAuth flow routes: login → (provider consent) → callback → session.

Works end-to-end with the mock provider today; drop in real client credentials to switch
to Google/Apple with no route changes.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth.providers import get_provider
from app.config import Settings, get_settings
from app.db.deps import get_user_store
from app.db.users import UserStore

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


def _safe_next(raw: str | None) -> str:
    """Only allow same-site relative redirects (prevent open-redirect)."""
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


@router.get("/login")
async def login(
    request: Request,
    provider: str = "google",
    next: str | None = None,
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = _safe_next(next)
    redirect_uri = str(request.url_for("auth_callback"))
    url = get_provider(settings, provider).authorize_url(state=state, redirect_uri=redirect_uri)
    return RedirectResponse(url, status_code=307)


@router.get("/mock-consent", response_class=HTMLResponse)
async def mock_consent(
    request: Request,
    state: str,
    redirect_uri: str,
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    """Stand-in consent screen used only by MockProvider."""
    return templates.TemplateResponse(
        request,
        "mock_consent.html",
        {"settings": settings, "state": state, "redirect_uri": redirect_uri},
    )


@router.api_route("/callback", methods=["GET", "POST"], name="auth_callback")
async def callback(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: UserStore = Depends(get_user_store),
    code: str = "",
    state: str = "",
    provider: str = "google",
) -> RedirectResponse:
    # mock consent posts the chosen handle as a form field
    if request.method == "POST":
        form = await request.form()
        code = str(form.get("code") or code)
        state = str(form.get("state") or state)

    expected_state = request.session.get("oauth_state")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        return RedirectResponse("/?auth_error=state", status_code=303)

    oauth_user = await get_provider(settings, provider).exchange(
        code=code, redirect_uri=str(request.url_for("auth_callback"))
    )
    user = await store.upsert(
        provider=oauth_user.provider,
        subject=oauth_user.subject,
        email=oauth_user.email,
        name=oauth_user.name,
    )

    next_url = _safe_next(request.session.get("oauth_next"))
    request.session.pop("oauth_state", None)
    request.session.pop("oauth_next", None)
    request.session["user_id"] = user.id
    # 303 → the browser issues a GET to the destination (don't replay the POST)
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.pop("user_id", None)
    return RedirectResponse("/", status_code=303)
