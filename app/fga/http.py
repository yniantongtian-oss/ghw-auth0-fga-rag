"""HTTP client for Auth0 FGA and a local OpenFGA server.

Both speak the same store API. Auth0 FGA adds a client-credentials token when
FGA_CLIENT_ID is set. Local OpenFGA usually runs with no auth.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import Settings
from app.fga.dsl import Model, model_to_json
from app.fga.memory import Tuple


class FgaError(RuntimeError):
    """The authorization service could not answer. Callers fail closed."""


class HttpFga:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        if not settings.fga_api_url:
            raise FgaError("FGA_API_URL is not set")
        self.settings = settings
        self._base = settings.fga_api_url.rstrip("/")
        self._client = client or httpx.Client(timeout=10.0)
        self._owns_client = client is None
        self.store_id = settings.fga_store_id
        self.model_id = settings.fga_authorization_model_id
        self._token = ""
        self._token_until = 0.0

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def batch_check(self, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        if not objects:
            return {}
        checks = []
        mapping: dict[str, str] = {}
        for index, obj in enumerate(objects):
            correlation_id = f"c{index}"
            mapping[correlation_id] = obj
            checks.append(
                {
                    "correlation_id": correlation_id,
                    "tuple_key": {"user": user, "relation": relation, "object": obj},
                }
            )
        body: dict[str, Any] = {"checks": checks}
        if self.model_id:
            body["authorization_model_id"] = self.model_id
        try:
            payload = self._request("POST", self._store_path("/batch-check"), body)
        except FgaError as exc:
            message = str(exc).lower()
            if "404" in message or "undefined_endpoint" in message:
                return self._check_each(user, relation, objects)
            raise
        result = payload.get("result") or {}
        decisions: dict[str, bool] = {}
        for correlation_id, obj in mapping.items():
            item = result.get(correlation_id) or {}
            message = ""
            error = item.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
            decisions[obj] = bool(item.get("allowed")) and not message.strip()
        return decisions

    def list_objects(self, user: str, relation: str, object_type: str) -> list[str]:
        body: dict[str, Any] = {"user": user, "relation": relation, "type": object_type}
        if self.model_id:
            body["authorization_model_id"] = self.model_id
        payload = self._request("POST", self._store_path("/list-objects"), body)
        objects = payload.get("objects") or []
        return [str(item) for item in objects]

    def check(self, user: str, relation: str, obj: str) -> bool:
        return self.batch_check(user, relation, [obj]).get(obj, False)

    def _check_each(self, user: str, relation: str, objects: list[str]) -> dict[str, bool]:
        """Older OpenFGA builds expose /check but not /batch-check. Still pre-LLM."""
        decisions: dict[str, bool] = {}
        for obj in objects:
            body: dict[str, Any] = {
                "tuple_key": {"user": user, "relation": relation, "object": obj}
            }
            if self.model_id:
                body["authorization_model_id"] = self.model_id
            payload = self._request("POST", self._store_path("/check"), body)
            decisions[obj] = bool(payload.get("allowed"))
        return decisions

    def bootstrap(self, model: Model, tuples: list[Tuple], store_name: str) -> None:
        """Create a local store when needed, write the model, then write tuples."""
        if not self.store_id:
            self.store_id = self._find_or_create_store(store_name)
        written = self._request(
            "POST",
            self._store_path("/authorization-models"),
            model_to_json(model),
        )
        model_id = written.get("authorization_model_id") or written.get("id")
        if not model_id:
            raise FgaError("authorization model write did not return an id")
        self.model_id = str(model_id)
        for item in tuples:
            self._write_tuple(item)

    def _write_tuple(self, item: Tuple) -> None:
        body: dict[str, Any] = {
            "writes": {"tuple_keys": [item.as_dict()]},
            "authorization_model_id": self.model_id,
        }
        try:
            self._request("POST", self._store_path("/write"), body)
        except FgaError as exc:
            message = str(exc).lower()
            if "already exists" in message:
                return
            raise

    def _find_or_create_store(self, store_name: str) -> str:
        payload = self._request("GET", "/stores", None)
        for store in payload.get("stores") or []:
            if store.get("name") == store_name and store.get("id"):
                return str(store["id"])
        created = self._request("POST", "/stores", {"name": store_name})
        store_id = created.get("id")
        if not store_id:
            raise FgaError("store create did not return an id")
        return str(store_id)

    def _store_path(self, suffix: str) -> str:
        if not self.store_id:
            raise FgaError("FGA store id is not set")
        return f"/stores/{self.store_id}{suffix}"

    def _request(self, method: str, path: str, body: dict | None) -> dict:
        headers: dict[str, str] = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.settings.fga_client_id:
            headers["Authorization"] = f"Bearer {self._access_token()}"
        try:
            response = self._client.request(
                method,
                self._base + path,
                headers=headers,
                json=body if body is not None else None,
            )
        except httpx.HTTPError as exc:
            raise FgaError(f"FGA request failed: {exc}") from exc
        if response.status_code >= 400:
            detail = response.text[:500]
            raise FgaError(f"FGA {method} {path} returned {response.status_code}: {detail}")
        if not response.content:
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise FgaError("FGA returned a non-object response")
        return data

    def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_until:
            return self._token
        issuer = self.settings.fga_api_token_issuer.rstrip("/")
        if not issuer.startswith("http"):
            issuer = "https://" + issuer
        audience = self.settings.fga_api_audience or (self._base + "/")
        try:
            response = self._client.post(
                issuer + "/oauth/token",
                json={
                    "client_id": self.settings.fga_client_id,
                    "client_secret": self.settings.fga_client_secret,
                    "audience": audience,
                    "grant_type": "client_credentials",
                },
            )
        except httpx.HTTPError as exc:
            raise FgaError(f"FGA token request failed: {exc}") from exc
        if response.status_code >= 400:
            raise FgaError(f"FGA token request returned {response.status_code}")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise FgaError("FGA token response had no access_token")
        expires_in = int(payload.get("expires_in") or 300)
        self._token = str(token)
        self._token_until = now + max(30, expires_in - 30)
        return self._token
