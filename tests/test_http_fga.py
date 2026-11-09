import json

import httpx

from app.config import Settings
from app.fga.http import HttpFga


def _settings(**overrides) -> Settings:
    base = dict(
        fga_api_url="http://openfga.test",
        fga_store_id="01STORE",
        fga_auto_bootstrap=False,
    )
    base.update(overrides)
    return Settings(**base)


def test_batch_check_fails_closed_on_item_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["checks"][0]["tuple_key"]["relation"] == "viewer"
        return httpx.Response(
            200,
            json={
                "result": {
                    "c0": {"allowed": True, "error": {"message": ""}},
                    "c1": {"allowed": True, "error": {"message": "throttled"}},
                    "c2": {"allowed": False, "error": {"message": ""}},
                }
            },
        )

    client = HttpFga(_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    decisions = client.batch_check(
        "user:alice",
        "viewer",
        ["document:salary_bands_2026", "document:missing", "document:handbook"],
    )
    assert decisions == {
        "document:salary_bands_2026": True,
        "document:missing": False,
        "document:handbook": False,
    }


def test_auth0_fga_sends_a_bearer_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            payload = json.loads(request.content.decode())
            assert payload["audience"] == "https://api.us1.fga.dev/"
            assert payload["client_id"] == "cid"
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 600})
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json={"objects": ["document:salary_bands_2026"]},
        )

    settings = _settings(
        fga_api_url="https://api.us1.fga.dev",
        fga_client_id="cid",
        fga_client_secret="sec",
        fga_api_audience="https://api.us1.fga.dev/",
        fga_api_token_issuer="https://auth.fga.dev",
    )
    client = HttpFga(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    objects = client.list_objects("user:alice", "viewer", "document")
    assert objects == ["document:salary_bands_2026"]
    assert seen["auth"] == "Bearer tok-1"


def test_missing_batch_endpoint_falls_back_to_check():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/batch-check"):
            return httpx.Response(404, json={"code": "undefined_endpoint", "message": "no"})
        if request.url.path.endswith("/check"):
            body = json.loads(request.content.decode())
            allowed = body["tuple_key"]["object"] == "document:employee_handbook"
            return httpx.Response(200, json={"allowed": allowed})
        return httpx.Response(500, json={"message": "unexpected"})

    client = HttpFga(_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    decisions = client.batch_check(
        "user:bob",
        "viewer",
        ["document:employee_handbook", "document:salary_bands_2026"],
    )
    assert decisions["document:employee_handbook"] is True
    assert decisions["document:salary_bands_2026"] is False
