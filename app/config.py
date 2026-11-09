"""Runtime configuration. The process runs fully offline when FGA and LLM are unset."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTH0_DOMAIN = "dev-wvxvhbnjrgvgn26x.us.auth0.com"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE lines that are not already in the environment."""
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    auth0_domain: str = DEFAULT_AUTH0_DOMAIN
    auth0_client_id: str = ""
    auth0_client_secret: str = ""
    auth0_callback_url: str = "http://localhost:8000/callback"
    session_secret: str = "dev-session-secret-change-me"
    session_https_only: bool = False
    dev_user_switcher: bool = True
    fga_api_url: str = ""
    fga_store_id: str = ""
    fga_store_name: str = "hearth-hr"
    fga_client_id: str = ""
    fga_client_secret: str = ""
    fga_api_audience: str = ""
    fga_api_token_issuer: str = "https://auth.fga.dev"
    fga_authorization_model_id: str = ""
    fga_auto_bootstrap: bool = False
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    @property
    def auth0_enabled(self) -> bool:
        return bool(self.auth0_client_id and self.auth0_client_secret)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def fga_backend_label(self) -> str:
        if not self.fga_api_url:
            return "in-memory OpenFGA model"
        if self.fga_client_id:
            return "Auth0 FGA"
        return "OpenFGA"

    @classmethod
    def from_env(cls) -> Settings:
        load_env_file()
        auth0_client_id = os.environ.get("AUTH0_CLIENT_ID", "").strip()
        fga_api_url = os.environ.get("FGA_API_URL", "").strip()
        fga_client_id = os.environ.get("FGA_CLIENT_ID", "").strip()
        llm_key = os.environ.get("LLM_API_KEY", "").strip() or os.environ.get(
            "OPENAI_API_KEY", ""
        ).strip()
        llm_base = os.environ.get("LLM_BASE_URL", "").strip()
        if llm_key and not llm_base:
            llm_base = "https://api.openai.com/v1"
        return cls(
            auth0_domain=os.environ.get("AUTH0_DOMAIN", DEFAULT_AUTH0_DOMAIN).strip()
            or DEFAULT_AUTH0_DOMAIN,
            auth0_client_id=auth0_client_id,
            auth0_client_secret=os.environ.get("AUTH0_CLIENT_SECRET", "").strip(),
            auth0_callback_url=os.environ.get(
                "AUTH0_CALLBACK_URL", "http://localhost:8000/callback"
            ).strip(),
            session_secret=os.environ.get("SESSION_SECRET", "dev-session-secret-change-me"),
            session_https_only=_flag("SESSION_HTTPS_ONLY", False),
            dev_user_switcher=_flag("DEV_USER_SWITCHER", not bool(auth0_client_id)),
            fga_api_url=fga_api_url,
            fga_store_id=os.environ.get("FGA_STORE_ID", "").strip(),
            fga_store_name=os.environ.get("FGA_STORE_NAME", "hearth-hr").strip() or "hearth-hr",
            fga_client_id=fga_client_id,
            fga_client_secret=os.environ.get("FGA_CLIENT_SECRET", "").strip(),
            fga_api_audience=os.environ.get("FGA_API_AUDIENCE", "").strip(),
            fga_api_token_issuer=os.environ.get(
                "FGA_API_TOKEN_ISSUER", "https://auth.fga.dev"
            ).strip()
            or "https://auth.fga.dev",
            fga_authorization_model_id=os.environ.get("FGA_AUTHORIZATION_MODEL_ID", "").strip(),
            fga_auto_bootstrap=_flag(
                "FGA_AUTO_BOOTSTRAP", bool(fga_api_url) and not bool(fga_client_id)
            ),
            llm_base_url=llm_base,
            llm_api_key=llm_key,
            llm_model=os.environ.get("LLM_MODEL", "").strip() or "gpt-4o-mini",
        )
