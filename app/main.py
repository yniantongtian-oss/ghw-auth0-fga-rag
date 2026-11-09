"""HTTP API and static UI for Hearth."""

from __future__ import annotations

import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.sessions import SessionMiddleware

from app.config import ROOT, Settings
from app.corpus import Employee, load_model_text, load_tuples
from app.identity import map_auth0_claims, normalize_user_id
from app.oauth import Auth0Error, authorize_url, exchange_code, fetch_userinfo, logout_url
from app.runtime import build_engine

STATIC_DIR = ROOT / "static"

_FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="4" fill="#16352b"/>
<path d="M8 23V9h3.2l4.8 8.2L20.8 9H24v14h-2.6v-8.7L17.2 23h-2.4l-4.2-8.7V23H8z" fill="#f4efe6"/>
</svg>"""


class AskBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    question: str = Field(min_length=1, max_length=2000)


class SwitchBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    engine = build_engine(settings)
    app = FastAPI(title="Hearth", version="1.0.0")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        same_site="lax",
        https_only=settings.session_https_only,
        max_age=60 * 60 * 12,
    )
    app.state.settings = settings
    app.state.engine = engine

    @app.middleware("http")
    async def no_store_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/favicon.svg")
    def favicon() -> Response:
        return Response(_FAVICON, media_type="image/svg+xml")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "fga": settings.fga_backend_label}

    @app.get("/api/config")
    def config() -> dict:
        return {
            "auth0": settings.auth0_enabled,
            "devSwitcher": settings.dev_user_switcher,
            "backend": settings.fga_backend_label,
            "llm": settings.llm_enabled,
            "auth0Domain": settings.auth0_domain if settings.auth0_enabled else "",
        }

    @app.get("/api/model")
    def model() -> PlainTextResponse:
        return PlainTextResponse(load_model_text())

    @app.get("/api/tuples")
    def tuples() -> dict:
        return {"tuples": [item.as_dict() for item in load_tuples()]}

    @app.get("/api/dev/users")
    def dev_users() -> dict:
        if not settings.dev_user_switcher:
            raise HTTPException(status_code=404, detail="dev switcher is disabled")
        return {"users": [user.as_dict() for user in engine.users]}

    @app.post("/auth/dev/switch")
    def dev_switch(body: SwitchBody, request: Request) -> dict:
        if not settings.dev_user_switcher:
            raise HTTPException(status_code=404, detail="dev switcher is disabled")
        user_id = normalize_user_id(body.user_id)
        if user_id is None or user_id not in engine.users_by_id:
            raise HTTPException(status_code=404, detail="unknown user")
        request.session["user_id"] = user_id
        request.session["auth_method"] = "dev"
        request.session.pop("email", None)
        return {"user": engine.users_by_id[user_id].as_dict()}

    @app.get("/login")
    def login(request: Request) -> RedirectResponse:
        if not settings.auth0_enabled:
            raise HTTPException(status_code=400, detail="Auth0 is not configured")
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        return RedirectResponse(authorize_url(settings, state), status_code=302)

    @app.get("/callback")
    def callback(request: Request) -> RedirectResponse:
        if not settings.auth0_enabled:
            raise HTTPException(status_code=400, detail="Auth0 is not configured")
        if request.query_params.get("error"):
            raise HTTPException(status_code=400, detail="Auth0 sign-in was cancelled")
        state = request.query_params.get("state") or ""
        expected = str(request.session.pop("oauth_state", "") or "")
        if not _states_match(state, expected):
            raise HTTPException(status_code=400, detail="invalid oauth state")
        code = request.query_params.get("code") or ""
        if not code:
            raise HTTPException(status_code=400, detail="missing code")
        try:
            token = exchange_code(settings, code)
            claims = fetch_userinfo(settings, token)
        except Auth0Error as exc:
            raise HTTPException(status_code=401, detail="Auth0 sign-in failed") from exc
        user_id = map_auth0_claims(claims, set(engine.users_by_id))
        request.session["user_id"] = user_id
        request.session["auth_method"] = "auth0"
        email = claims.get("email")
        if isinstance(email, str):
            request.session["email"] = email
        return RedirectResponse("/", status_code=302)

    @app.get("/logout")
    def logout(request: Request) -> RedirectResponse:
        method = request.session.get("auth_method")
        request.session.clear()
        if method == "auth0" and settings.auth0_enabled:
            return RedirectResponse(logout_url(settings), status_code=302)
        return RedirectResponse("/", status_code=302)

    @app.get("/api/me")
    def me(request: Request) -> dict:
        user = _session_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="sign in required")
        return {
            "user": user.as_dict(),
            "email": request.session.get("email") or "",
            "auth_method": request.session.get("auth_method") or "",
            "backend": settings.fga_backend_label,
            "indexed_document_count": len(engine.documents),
            "visible_documents": engine.visible_documents(user.id),
        }

    @app.post("/api/ask")
    def ask(body: AskBody, request: Request) -> dict:
        user = _session_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="sign in required")
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="question is required")
        # The principal is the session. Body fields other than question are ignored.
        result = engine.answer(user.id, question)
        return result.public_dict()

    def _session_user(request: Request) -> Employee | None:
        raw = request.session.get("user_id")
        if not isinstance(raw, str) or not raw:
            return None
        user_id = normalize_user_id(raw)
        if user_id is None:
            return None
        known = engine.users_by_id.get(user_id)
        if known is not None:
            return known
        return Employee(
            id=user_id,
            name=user_id,
            title="Authenticated user",
            department="unassigned",
            role="none",
        )

    return app


def _states_match(state: str, expected: str) -> bool:
    if not state or not expected or len(state) != len(expected):
        return False
    return secrets.compare_digest(state, expected)


app = create_app()
