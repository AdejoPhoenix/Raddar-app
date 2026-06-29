"""OAuth providers behind a single interface.

`MockProvider` lets the entire Lazy Wall flow run and be tested with no real credentials:
it bounces the user to an in-app consent page. `GoogleProvider`/`AppleProvider` are real
stubs — fill in the token/userinfo exchange and supply client credentials to go live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx

from app.config import Settings


@dataclass
class OAuthUser:
    provider: str
    subject: str
    email: str | None = None
    name: str | None = None


class OAuthProvider(Protocol):
    name: str

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        """Where to send the browser to begin consent."""
        ...

    async def exchange(self, *, code: str, redirect_uri: str) -> OAuthUser:
        """Exchange the returned code for a verified user identity."""
        ...


class MockProvider:
    """No real network calls — routes through our own consent page. Dev/test only."""

    name = "mock"

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        qs = urlencode({"state": state, "redirect_uri": redirect_uri})
        return f"/auth/mock-consent?{qs}"

    async def exchange(self, *, code: str, redirect_uri: str) -> OAuthUser:
        # In mock mode the "code" is just the chosen display name from the consent page.
        handle = code or "guest"
        return OAuthUser(
            provider="mock",
            subject=f"mock:{handle.lower()}",
            email=f"{handle.lower()}@example.com",
            name=handle,
        )


class GoogleProvider:
    name = "google"
    _AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
    _TOKEN = "https://oauth2.googleapis.com/token"
    _USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        qs = urlencode(
            {
                "client_id": self._settings.google_client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
            }
        )
        return f"{self._AUTH}?{qs}"

    async def exchange(self, *, code: str, redirect_uri: str) -> OAuthUser:  # pragma: no cover
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_resp = await client.post(
                self._TOKEN,
                data={
                    "code": code,
                    "client_id": self._settings.google_client_id,
                    "client_secret": self._settings.google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            token_resp.raise_for_status()
            access_token = token_resp.json()["access_token"]
            info = await client.get(
                self._USERINFO, headers={"Authorization": f"Bearer {access_token}"}
            )
            info.raise_for_status()
            data = info.json()
        return OAuthUser(
            provider="google",
            subject=data["sub"],
            email=data.get("email"),
            name=data.get("name"),
        )


def get_provider(settings: Settings, name: str) -> OAuthProvider:
    """Always returns the mock provider until real credentials are configured."""
    if settings.use_mock_oauth:
        return MockProvider()
    if name == "google":
        return GoogleProvider(settings)
    # Apple follows the same shape; mock until implemented.
    return MockProvider()
