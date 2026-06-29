"""W5 — security headers + rate limiting."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_security_headers_present() -> None:
    c = TestClient(app)
    r = c.get("/")
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Referrer-Policy" in r.headers
    assert "Permissions-Policy" in r.headers


def test_csp_allows_maplibre_and_tiles() -> None:
    """Regression guard: MapLibre needs the OSM tile host (img+connect) and blob workers."""
    csp = TestClient(app).get("/").headers["Content-Security-Policy"]
    assert "https://unpkg.com" in csp  # maplibre script/style
    assert "tile.openstreetmap.org" in csp  # raster tiles
    assert "worker-src 'self' blob:" in csp  # maplibre worker
    assert "blob:" in csp.split("connect-src")[0]  # blob present (worker/child/img)
    # tile host must be reachable for both image loads and fetch
    img = csp.split("img-src")[1].split(";")[0]
    conn = csp.split("connect-src")[1].split(";")[0]
    assert "tile.openstreetmap.org" in img and "tile.openstreetmap.org" in conn


def test_rate_limit_trips_on_api() -> None:
    # build an app with a tiny limit so the test is fast and deterministic
    from app.config import get_settings

    get_settings.cache_clear()
    import os

    os.environ["RATE_LIMIT_PER_MINUTE"] = "5"
    try:
        from importlib import reload

        import app.main as main_module

        reload(main_module)
        c = TestClient(main_module.app)
        codes = [c.get("/api/events").status_code for _ in range(7)]
        assert 429 in codes, f"expected a 429 within {codes}"
        assert codes[:5] == [200] * 5
    finally:
        os.environ.pop("RATE_LIMIT_PER_MINUTE", None)
        get_settings.cache_clear()
        from importlib import reload

        import app.main as main_module

        reload(main_module)
