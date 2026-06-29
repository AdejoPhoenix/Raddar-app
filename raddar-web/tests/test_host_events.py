"""User-hosted events — Lazy Wall gating, creation, discovery, live-location radius (memory backend)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import app.db.repository as repo_module
from app.config import get_settings
from app.db.users import bookmarks, users
from app.main import app


@pytest.fixture(autouse=True)
def _clear_state() -> None:
    users._by_id.clear()
    users._by_identity.clear()
    bookmarks._store.clear()
    repo_module._hosted_events.clear()


def _login(c: TestClient, handle: str = "host") -> dict:
    consent = c.get("/auth/login", params={"provider": "google", "next": "/"})
    state = re.search(r'name="state" value="([^"]+)"', consent.text).group(1)
    c.post("/auth/callback", data={"code": handle, "state": state, "provider": "mock"})
    return c.get("/api/session").json()


def _host(c: TestClient, csrf: str, **overrides) -> dict:
    body = {"title": "My pin", "category": "Food", **_DUBLIN, **overrides}
    res = c.post("/api/events", json=body, headers={"X-CSRF-Token": csrf})
    assert res.status_code == 201, res.text
    return res.json()


# pin at the Dublin anchor, with the live GPS at the same spot (passes the radius check)
_DUBLIN = {"lat": 53.3498, "lng": -6.2603, "user_lat": 53.3498, "user_lng": -6.2603}


def test_anonymous_cannot_host() -> None:
    c = TestClient(app)
    sess = c.get("/api/session").json()
    res = c.post(
        "/api/events",
        json={"title": "Taco truck", "category": "Food", **_DUBLIN},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert res.status_code == 401
    assert res.json()["detail"]["login_url"].startswith("/auth/login")


def test_host_event_then_visible_on_map() -> None:
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    res = c.post(
        "/api/events",
        json={"title": "Taco truck on Dame St", "category": "Food",
              "cost_tier": "€", "duration_minutes": 120, **_DUBLIN},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert res.status_code == 201
    created = res.json()
    assert created["title"] == "Taco truck on Dame St"
    assert created["is_ending_soon"] is False

    # appears in discovery near the Dublin anchor
    titles = [e["title"] for e in c.get("/api/events").json()]
    assert "Taco truck on Dame St" in titles


def test_host_near_live_location_allowed_anywhere() -> None:
    # Not Dublin-locked: a pin near the user's live GPS is accepted wherever they are (London).
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    res = c.post(
        "/api/events",
        json={
            "title": "Gig in London", "category": "Music",
            "lat": 51.5074, "lng": -0.1278,        # pin
            "user_lat": 51.5076, "user_lng": -0.1278,  # ~22m north → within 70m
        },
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert res.status_code == 201
    assert res.json()["lat"] == 51.5074


def test_host_far_from_live_location_rejected() -> None:
    # Pin >70m from the user's live GPS is rejected — can't host across town/country.
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    res = c.post(
        "/api/events",
        json={
            "title": "Remote pin", "category": "Music",
            "lat": 53.3498, "lng": -6.2603,           # pin at Dublin anchor
            "user_lat": 53.3600, "user_lng": -6.2603,  # ~1.1km north
        },
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert res.status_code == 422
    assert "current location" in res.json()["detail"]


def test_host_per_user_quota_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "host_max_active_per_user", 2)
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    headers = {"X-CSRF-Token": sess["csrf_token"]}
    body = {"title": "Pop-up", "category": "Food", **_DUBLIN}

    # first two pins are fine
    for _ in range(2):
        assert c.post("/api/events", json=body, headers=headers).status_code == 201
    # the third exceeds the quota
    res = c.post("/api/events", json=body, headers=headers)
    assert res.status_code == 429
    assert "active pins" in res.json()["detail"]


def test_session_reports_hosting_quota() -> None:
    c = TestClient(app, follow_redirects=True)
    # anonymous → no hosting info
    assert c.get("/api/session").json()["hosting"] is None

    sess = _login(c)
    before = c.get("/api/session").json()["hosting"]
    assert before["used"] == 0
    assert before["limit"] == get_settings().host_max_active_per_user

    c.post(
        "/api/events",
        json={"title": "Pop-up", "category": "Food", **_DUBLIN},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert c.get("/api/session").json()["hosting"]["used"] == 1


def test_delete_own_pin() -> None:
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    eid = _host(c, sess["csrf_token"])["event_id"]

    res = c.delete(f"/api/events/{eid}", headers={"X-CSRF-Token": sess["csrf_token"]})
    assert res.status_code == 204
    # gone from the user's pins and from the public detail page
    assert c.get(f"/event/{eid}").status_code == 410


def test_cannot_delete_someone_elses_pin() -> None:
    owner = TestClient(app, follow_redirects=True)
    owner_sess = _login(owner, "owner")
    eid = _host(owner, owner_sess["csrf_token"])["event_id"]

    other = TestClient(app, follow_redirects=True)
    other_sess = _login(other, "intruder")
    res = other.delete(f"/api/events/{eid}", headers={"X-CSRF-Token": other_sess["csrf_token"]})
    assert res.status_code == 403


def test_delete_missing_pin_404() -> None:
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    res = c.delete("/api/events/does-not-exist", headers={"X-CSRF-Token": sess["csrf_token"]})
    assert res.status_code == 404


def test_edit_own_pin() -> None:
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    eid = _host(c, sess["csrf_token"], title="Taco truck")["event_id"]

    res = c.patch(
        f"/api/events/{eid}",
        json={"title": "Burrito truck", "category": "Market", "cost_tier": "€"},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    assert res.status_code == 200
    out = res.json()
    assert out["title"] == "Burrito truck"
    assert out["category"] == "Market"
    assert out["cost_tier"] == "€"


def test_cannot_edit_someone_elses_pin() -> None:
    owner = TestClient(app, follow_redirects=True)
    owner_sess = _login(owner, "owner")
    eid = _host(owner, owner_sess["csrf_token"])["event_id"]

    other = TestClient(app, follow_redirects=True)
    other_sess = _login(other, "intruder")
    res = other.patch(
        f"/api/events/{eid}",
        json={"title": "Hijacked"},
        headers={"X-CSRF-Token": other_sess["csrf_token"]},
    )
    assert res.status_code == 403


def test_me_page_redirects_anonymous() -> None:
    c = TestClient(app, follow_redirects=False)
    res = c.get("/me")
    assert res.status_code == 303
    assert "/auth/login" in res.headers["location"]


def test_me_page_lists_saved_and_hosted() -> None:
    c = TestClient(app, follow_redirects=True)
    sess = _login(c)
    # a hosted pin
    eid = _host(c, sess["csrf_token"], title="My block party")["event_id"]
    # a saved (bookmarked) event — bookmark the pin itself for simplicity
    c.post(
        "/api/bookmarks",
        json={"event_id": eid},
        headers={"X-CSRF-Token": sess["csrf_token"]},
    )
    page = c.get("/me")
    assert page.status_code == 200
    assert "Your Raddar" in page.text
    assert "My block party" in page.text


def test_host_requires_csrf() -> None:
    c = TestClient(app, follow_redirects=True)
    _login(c)
    res = c.post("/api/events", json={"title": "No CSRF", "category": "Food", **_DUBLIN})
    assert res.status_code == 403
