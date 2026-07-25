from fastapi.testclient import TestClient

from app.main import app


def test_index_served_with_required_csp_and_session_storage() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' "
        "'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self' data:"
    ) in response.text
    assert "localStorage" in response.text


def test_static_page_has_no_innerhtml() -> None:
    response = TestClient(app).get("/")

    assert "innerHTML" not in response.text
