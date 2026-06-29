"""W4 — Lazy Wall: anonymous browsing, OAuth (mock), CSRF, bookmark persistence."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.users import bookmarks, users
from app.main import app


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    users._by_id.clear()
    users._by_identity.clear()
    bookmarks._store.clear()


def _client() -> TestClient:
    # follow_redirects so the 307 OAuth chain resolves to the final page
    return TestClient(app, follow_redirects=True)


def test_anonymous_can_browse_event_detail() -> None:
    c = _client()
    assert c.get("/api/events").status_code == 200
    eid = c.get("/api/events").json()[0]["event_id"]
    assert c.get(f"/event/{eid}").status_code == 200


def test_lazy_wall_blocks_anonymous_bookmark_with_login_url() -> None:
    c = TestClient(app)  # no redirect following — inspect the 401
    sess = c.get("/api/session").json()
    res = c.post(
        "/api/bookmarks",
        json={"event_id": "seed-000"},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert res.status_code == 401
    detail = res.json()["detail"]
    assert detail["auth_required"] is True
    assert detail["login_url"].startswith("/auth/login")


def test_mock_oauth_login_then_bookmark_persists() -> None:
    c = _client()

    # 1) start login → mock consent page
    consent = c.get("/auth/login", params={"provider": "google", "next": "/event/seed-000"})
    assert consent.status_code == 200
    assert "Mock sign-in" in consent.text

    # 2) grab state from the session and complete consent
    state = c.cookies and dict(c.cookies)  # cookie present
    # pull state out of the rendered form
    import re

    m = re.search(r'name="state" value="([^"]+)"', consent.text)
    assert m, "state token missing from consent form"
    state_token = m.group(1)

    cb = c.post("/auth/callback", data={"code": "alex", "state": state_token, "provider": "mock"})
    assert cb.status_code == 200  # redirected (followed) to /event/seed-000

    # 3) now authenticated
    sess = c.get("/api/session").json()
    assert sess["authenticated"] is True
    assert sess["user"]["name"] == "alex"

    # 4) bookmark with CSRF token → persists
    add = c.post(
        "/api/bookmarks",
        json={"event_id": "seed-000"},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert add.status_code == 201
    assert "seed-000" in add.json()["event_ids"]
    assert c.get("/api/bookmarks").json()["event_ids"] == ["seed-000"]


def test_csrf_required_for_mutation() -> None:
    c = _client()
    # authenticate via mock
    consent = c.get("/auth/login", params={"provider": "google", "next": "/"})
    import re

    state_token = re.search(r'name="state" value="([^"]+)"', consent.text).group(1)
    c.post("/auth/callback", data={"code": "sam", "state": state_token, "provider": "mock"})

    # missing CSRF header → 403 (and authenticated, so not 401)
    res = c.post("/api/bookmarks", json={"event_id": "seed-000"})
    assert res.status_code == 403


def test_logout_clears_session() -> None:
    c = _client()
    consent = c.get("/auth/login", params={"provider": "google", "next": "/"})
    import re

    state_token = re.search(r'name="state" value="([^"]+)"', consent.text).group(1)
    c.post("/auth/callback", data={"code": "kim", "state": state_token, "provider": "mock"})
    assert c.get("/api/session").json()["authenticated"] is True

    c.post("/auth/logout")
    assert c.get("/api/session").json()["authenticated"] is False
