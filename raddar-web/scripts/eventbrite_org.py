"""Discover your Eventbrite organization id(s) from the Private token.

Reads EVENTBRITE_TOKEN from the environment / .env (never printed), calls the Eventbrite API,
and prints only the org id + name so you can set EVENTBRITE_ORGANIZATION_ID.

Usage:  python -m scripts.eventbrite_org
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from app.config import get_settings


async def main() -> None:
    settings = get_settings()
    if not settings.eventbrite_token:
        print("EVENTBRITE_TOKEN is not set (add it to .env), then re-run.", file=sys.stderr)
        raise SystemExit(1)

    async with httpx.AsyncClient(
        base_url="https://www.eventbriteapi.com/v3",
        headers={"Authorization": f"Bearer {settings.eventbrite_token}"},
        timeout=10.0,
    ) as client:
        resp = await client.get("/users/me/organizations/")
        if resp.status_code == 401:
            print("401 Unauthorized — the token is invalid or lacks scope.", file=sys.stderr)
            raise SystemExit(1)
        resp.raise_for_status()
        orgs = resp.json().get("organizations", [])

    if not orgs:
        print("No organizations on this token.")
        return
    print("Organizations found:")
    for org in orgs:
        print(f"  EVENTBRITE_ORGANIZATION_ID={org['id']}   # {org.get('name', '')}")


if __name__ == "__main__":
    asyncio.run(main())
