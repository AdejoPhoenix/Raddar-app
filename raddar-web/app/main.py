"""Raddar web — FastAPI application entrypoint.

Run locally:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.middleware.sessions import SessionMiddleware

from app.api.bookmarks import router as bookmarks_router
from app.api.events import router as api_router
from app.api.session import router as session_router
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.db.base import init_models
from app.middleware import RateLimitMiddleware, SecurityHeadersMiddleware
from app.web.routes import router as web_router

logger.remove()
logger.add(sys.stderr, level="INFO", serialize=False)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.db_backend == "postgres" and settings.auto_create_tables:
        await init_models()  # dev convenience; production uses `alembic upgrade head`
        logger.info("Postgres schema ready (create_all)")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

    # --- Middleware (outermost first) ---
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    app.add_middleware(RateLimitMiddleware, limit_per_minute=settings.rate_limit_per_minute)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.cookie_secure,
        same_site="lax",
        max_age=settings.session_max_age,
    )

    app.mount("/static", StaticFiles(directory="static"), name="static")

    # --- Routes ---
    app.include_router(api_router)
    app.include_router(session_router)
    app.include_router(bookmarks_router)
    app.include_router(auth_router)
    app.include_router(web_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "city": settings.city_name, "backend": settings.db_backend}

    logger.info(
        "Raddar web ready — city={} backend={} oauth={}",
        settings.city_name,
        settings.db_backend,
        "mock" if settings.use_mock_oauth else "live",
    )
    return app


app = create_app()
