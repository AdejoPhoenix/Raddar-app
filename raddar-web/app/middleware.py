"""W5 hardening middleware: security headers + a simple per-IP rate limiter for /api/*."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# CSP permits MapLibre (unpkg script/style + blob worker), OSM raster tiles (img + fetch),
# and the small inline bootstrap script. Tighten with per-request nonces if the inline
# script is later externalized.
_OSM = "https://tile.openstreetmap.org https://*.tile.openstreetmap.org"
_CSP = (
    "default-src 'self'; "
    f"img-src 'self' data: blob: {_OSM}; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    f"connect-src 'self' {_OSM}; "
    "worker-src 'self' blob:; "
    "child-src blob:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(self), camera=(), microphone=()"
        )
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter on /api/* keyed by client IP. In-memory (single process)."""

    def __init__(self, app, *, limit_per_minute: int, path_prefix: str = "/api") -> None:
        super().__init__(app)
        self._limit = limit_per_minute
        self._prefix = path_prefix
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not request.url.path.startswith(self._prefix):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = self._hits[ip]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= self._limit:
            return JSONResponse(
                {"detail": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        window.append(now)
        return await call_next(request)
