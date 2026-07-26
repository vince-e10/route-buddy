from contextlib import contextmanager
import warnings

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import registry
from app.routers.ws import manager, router


SESSION_ID = "00000000-0000-4000-8000-000000000000"

warnings.filterwarnings("ignore", category=DeprecationWarning, module="app.routers.ws")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="starlette.testclient")


class RecordingAgentService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.action_calls: list[tuple[str, str, str]] = []

    async def handle_user_message(self, session_id: str, text: str) -> None:
        self.calls.append((session_id, text))

    async def propose_action(self, session_id: str, action: str, target_id: str) -> None:
        self.action_calls.append((session_id, action, target_id))


@pytest.fixture(autouse=True)
def reset_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_agent_service", None)
    monkeypatch.setattr(registry, "_publisher", registry.NoopPublisher())
    manager._connections.clear()


@contextmanager
def app_client():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_invalid_session_id_is_rejected_before_accept() -> None:
    with app_client() as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect("/ws?session_id=not-a-uuid"):
                pass

    assert error.value.code == 4400


def test_user_message_is_dispatched_to_agent_service() -> None:
    service = RecordingAgentService()
    registry.set_agent_service(service)

    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json({"type": "user_msg", "text": "Find Changi Airport"})

    assert service.calls == [(SESSION_ID, "Find Changi Airport")]


@pytest.mark.parametrize(
    ("action", "target_id"),
    [("book", "fare-exact"), ("cancel", "uber:trip-exact")],
)
def test_action_request_uses_connection_session(action: str, target_id: str) -> None:
    service = RecordingAgentService()
    registry.set_agent_service(service)

    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json(
                {"type": "action_request", "action": action, "target_id": target_id}
            )

    assert service.action_calls == [(SESSION_ID, action, target_id)]


@pytest.mark.parametrize(
    "message",
    [
        {"type": "action_request", "action": "book", "target_id": ""},
        {"type": "action_request", "action": "book", "target_id": "x" * 201},
        {"type": "action_request", "action": "delete", "target_id": "x"},
        {"type": "action_request", "action": "book", "target_id": 1},
        {
            "type": "action_request",
            "action": "book",
            "target_id": "x",
            "session_id": SESSION_ID,
        },
    ],
)
def test_invalid_action_request_is_rejected_without_service_call(message: dict) -> None:
    service = RecordingAgentService()
    registry.set_agent_service(service)

    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json(message)
            assert socket.receive_json() == {
                "type": "error",
                "message": "invalid message",
            }

    assert service.action_calls == []


@pytest.mark.parametrize(
    ("invalid_action", "valid_message", "expected_action_calls", "expected_user_calls"),
    [
        (
            ["book"],
            {"type": "action_request", "action": "book", "target_id": "fare-valid"},
            [(SESSION_ID, "book", "fare-valid")],
            [],
        ),
        (
            {"value": "cancel"},
            {"type": "user_msg", "text": "still connected"},
            [],
            [(SESSION_ID, "still connected")],
        ),
    ],
)
def test_non_string_action_is_rejected_and_connection_recovers(
    invalid_action,
    valid_message,
    expected_action_calls,
    expected_user_calls,
) -> None:
    service = RecordingAgentService()
    registry.set_agent_service(service)

    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json(
                {
                    "type": "action_request",
                    "action": invalid_action,
                    "target_id": "target",
                }
            )
            assert socket.receive_json() == {
                "type": "error",
                "message": "invalid message",
            }
            socket.send_json(valid_message)

    assert service.action_calls == expected_action_calls
    assert service.calls == expected_user_calls


def test_invalid_type_and_malformed_json_return_errors_then_recover() -> None:
    service = RecordingAgentService()
    registry.set_agent_service(service)

    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json({"type": "bogus"})
            assert socket.receive_json() == {"type": "error", "message": "invalid message"}
            socket.send_text("not json")
            assert socket.receive_json() == {"type": "error", "message": "invalid message"}
            socket.send_json({"type": "user_msg", "text": "Find Changi Airport"})

    assert service.calls == [(SESSION_ID, "Find Changi Airport")]


def test_text_over_2000_characters_is_rejected() -> None:
    registry.set_agent_service(RecordingAgentService())

    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json({"type": "user_msg", "text": "x" * 2001})
            assert socket.receive_json() == {"type": "error", "message": "invalid message"}


def test_unavailable_agent_service_reports_error_then_connection_recovers() -> None:
    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            socket.send_json({"type": "user_msg", "text": "Find Changi Airport"})
            assert socket.receive_json() == {
                "type": "error",
                "message": "assistant not available",
            }
            socket.send_json({"type": "bogus"})
            assert socket.receive_json() == {"type": "error", "message": "invalid message"}


def test_startup_registers_manager_and_publish_reaches_connected_client() -> None:
    with app_client() as client:
        assert registry.get_publisher() is manager
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}") as socket:
            client.portal.call(
                manager.publish,
                SESSION_ID,
                {"type": "assistant_msg", "text": "Hello"},
            )
            assert socket.receive_json() == {"type": "assistant_msg", "text": "Hello"}


def test_normal_disconnect_removes_connection() -> None:
    with app_client() as client:
        with client.websocket_connect(f"/ws?session_id={SESSION_ID}"):
            assert SESSION_ID in manager._connections

    assert SESSION_ID not in manager._connections
