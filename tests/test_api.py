from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

SALARY = "SENTINEL_SALARY_L6_242000"
QUESTION = "What is the L6 engineering base salary band?"


def _client() -> TestClient:
    return TestClient(create_app(Settings()))


def test_switcher_and_salary_access_through_the_api():
    client = _client()
    assert client.get("/api/me").status_code == 401

    alice = client.post("/auth/dev/switch", json={"user_id": "alice"})
    assert alice.status_code == 200
    me = client.get("/api/me")
    assert me.status_code == 200
    visible = {item["id"] for item in me.json()["visible_documents"]}
    assert "salary_bands_2026" in visible

    allowed = client.post("/api/ask", json={"question": QUESTION, "user_id": "bob"})
    assert allowed.status_code == 200
    assert SALARY in allowed.text
    assert "242000" in allowed.text
    alice_salary = [row for row in allowed.json()["trace"] if row["doc_id"] == "salary_bands_2026"]
    assert alice_salary and alice_salary[0]["allowed"] is True
    assert alice_salary[0]["quoted"] is True

    bob = client.post("/auth/dev/switch", json={"user_id": "bob"})
    assert bob.status_code == 200
    bob_visible = {item["id"] for item in client.get("/api/me").json()["visible_documents"]}
    assert "salary_bands_2026" not in bob_visible
    assert "employee_handbook" in bob_visible

    denied = client.post("/api/ask", json={"question": QUESTION, "user_id": "alice"})
    assert denied.status_code == 200
    body = denied.json()
    assert SALARY not in denied.text
    assert "242000" not in denied.text
    salary_rows = [row for row in body["trace"] if row["doc_id"] == "salary_bands_2026"]
    assert salary_rows and salary_rows[0]["allowed"] is False
    assert salary_rows[0]["quoted"] is False
    assert salary_rows[0]["title"] is None
    assert all(row["quoted"] is False for row in body["trace"])
    assert all("excerpt" not in row for row in body["trace"])


def test_dev_switcher_can_be_disabled_and_auth0_redirects_to_the_tenant():
    app = create_app(
        Settings(
            auth0_client_id="client-id",
            auth0_client_secret="client-secret",
            dev_user_switcher=False,
        )
    )
    client = TestClient(app)
    assert client.get("/api/dev/users").status_code == 404
    assert client.post("/auth/dev/switch", json={"user_id": "alice"}).status_code == 404

    login = client.get("/login", follow_redirects=False)
    assert login.status_code == 302
    location = login.headers["location"]
    assert location.startswith("https://dev-wvxvhbnjrgvgn26x.us.auth0.com/authorize?")
    assert "client_id=client-id" in location

    rejected = client.get("/callback?code=abc&state=not-the-state", follow_redirects=False)
    assert rejected.status_code == 400


def test_home_page_renders():
    client = _client()
    page = client.get("/")
    assert page.status_code == 200
    assert "Hearth" in page.text
    assert "Batch check" in page.text or "batch check" in page.text
