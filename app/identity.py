"""Map an Auth0 login onto a directory user id. The profile label is not a permission."""

from __future__ import annotations

import re

_ID = re.compile(r"[a-z0-9_-]{1,64}")


def normalize_user_id(value: str) -> str | None:
    text = value.strip()
    if text.lower().startswith("user:"):
        text = text.split(":", 1)[1]
    text = text.strip().lower()
    if _ID.fullmatch(text):
        return text
    return None


def map_auth0_claims(claims: dict, known_ids: set[str]) -> str:
    """Resolve the FGA user id for an Auth0 ID token / userinfo payload.

    An explicit `fga_user` claim wins. A nickname or email local-part maps only
    when it is already a directory id. The display name is ignored, and a raw
    `sub` never collapses onto a demo user such as alice.
    """
    for key in ("https://hearth.northline.example/fga_user", "fga_user"):
        raw = claims.get(key)
        if isinstance(raw, str):
            normalized = normalize_user_id(raw)
            if normalized:
                return normalized
    for key in ("nickname", "preferred_username"):
        raw = claims.get(key)
        if isinstance(raw, str):
            normalized = normalize_user_id(raw)
            if normalized and normalized in known_ids:
                return normalized
    email = claims.get("email")
    if isinstance(email, str) and "@" in email:
        local = normalize_user_id(email.split("@", 1)[0])
        if local and local in known_ids:
            return local
    sub = claims.get("sub")
    if isinstance(sub, str) and sub.strip():
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "_", sub).lower()[:48]
        normalized = normalize_user_id(cleaned) or "unknown"
        return f"auth0_{normalized}"[:64]
    return "auth0_unknown"
