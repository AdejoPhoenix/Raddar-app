"""Session, current-user, and CSRF dependencies.

The Lazy Wall lives here: anonymous requests can read everything, but a mutation without a
session raises 401 carrying a `login_url` so the client can trigger single-tap OAuth.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Request, status

from app.db.deps import get_user_store
from app.db.users import User, UserStore

_CSRF_KEY = "csrf_token"


async def current_user(
    request: Request,
    store: UserStore = Depends(get_user_store),
) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return await store.get(user_id)


async def require_user(
    request: Request,
    user: User | None = Depends(current_user),
) -> User:
    """Lazy Wall gate — 401 + login_url when anonymous."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "auth_required": True,
                "login_url": f"/auth/login?next={request.url.path}",
            },
        )
    return user


def ensure_csrf_token(request: Request) -> str:
    """Issue (once per session) and return the CSRF token."""
    token = request.session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_CSRF_KEY] = token
    return token


def verify_csrf(request: Request) -> None:
    """Double-submit check: header must match the token stored in the session."""
    expected = request.session.get(_CSRF_KEY)
    provided = request.headers.get("X-CSRF-Token")
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")


async def require_user_csrf(
    request: Request,
    user: User = Depends(require_user),
) -> User:
    """Mutation guard: enforce the Lazy Wall (401 first), then CSRF (403)."""
    verify_csrf(request)  # 403 when token missing/mismatched
    return user
