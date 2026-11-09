"""Auth0 authorization-code login for the configured tenant."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from app.config import Settings


class Auth0Error(RuntimeError):
    pass


def authorize_url(settings: Settings, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.auth0_client_id,
        "redirect_uri": settings.auth0_callback_url,
        "scope": "openid profile email",
        "state": state,
    }
    return f"https://{settings.auth0_domain}/authorize?{urlencode(params)}"


def logout_url(settings: Settings) -> str:
    origin = settings.auth0_callback_url.rsplit("/", 1)[0] + "/"
    params = urlencode({"client_id": settings.auth0_client_id, "returnTo": origin})
    return f"https://{settings.auth0_domain}/v2/logout?{params}"


def exchange_code(settings: Settings, code: str) -> str:
    try:
        response = httpx.post(
            f"https://{settings.auth0_domain}/oauth/token",
            json={
                "grant_type": "authorization_code",
                "client_id": settings.auth0_client_id,
                "client_secret": settings.auth0_client_secret,
                "code": code,
                "redirect_uri": settings.auth0_callback_url,
            },
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise Auth0Error("token exchange failed") from exc
    if response.status_code >= 400:
        raise Auth0Error("token exchange was rejected")
    token = response.json().get("access_token")
    if not token:
        raise Auth0Error("token response had no access token")
    return str(token)


def fetch_userinfo(settings: Settings, access_token: str) -> dict:
    try:
        response = httpx.get(
            f"https://{settings.auth0_domain}/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as exc:
        raise Auth0Error("userinfo failed") from exc
    if response.status_code >= 400:
        raise Auth0Error("userinfo was rejected")
    payload = response.json()
    if not isinstance(payload, dict):
        raise Auth0Error("userinfo was not an object")
    return payload
