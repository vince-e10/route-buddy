from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "intentionally-broken-ci-proof"}


def test_static_index_served() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "Route Buddy" in response.text


def test_security_headers_are_present() -> None:
    response = TestClient(app).get("/healthz")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
