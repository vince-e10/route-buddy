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


def test_session_storage_value_is_validated_as_uuid_v4() -> None:
    response = TestClient(app).get("/")

    assert "const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;" in response.text
    assert "if (!UUID_V4.test(sessionId || \"\"))" in response.text
    assert "sessionId = crypto.randomUUID();" in response.text


def test_websocket_confirmation_resolution_outweighs_late_http_or_transport_results() -> None:
    response = TestClient(app).get("/")

    assert "function isConfirmationResult(result)" in response.text
    assert "if (!response.ok || !isConfirmationResult(result))" in response.text
    assert "if (confirmation.websocketResolved && !authoritative) return;" in response.text
    assert "resolveConfirmation(message.token, message.result, true);" in response.text
    assert "if (confirmation && !confirmation.websocketResolved)" in response.text
    assert 'resolveConfirmation(message.token, "failed");' not in response.text
