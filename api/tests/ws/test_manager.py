import pytest

from app.ws.manager import ConnectionManager


class FakeWebSocket:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.messages.append(message)


@pytest.mark.asyncio
async def test_publish_reaches_all_tabs_in_one_session_only() -> None:
    manager = ConnectionManager()
    first_tab = FakeWebSocket()
    second_tab = FakeWebSocket()
    other_session = FakeWebSocket()
    message = {"type": "assistant_msg", "text": "Hello"}

    await manager.connect("session-a", first_tab)
    await manager.connect("session-a", second_tab)
    await manager.connect("session-b", other_session)
    await manager.publish("session-a", message)

    assert first_tab.messages == [message]
    assert second_tab.messages == [message]
    assert other_session.messages == []


@pytest.mark.asyncio
async def test_publish_without_connections_is_a_noop() -> None:
    manager = ConnectionManager()

    await manager.publish("missing", {"type": "assistant_msg", "text": "Hello"})


@pytest.mark.asyncio
async def test_failed_send_evicts_socket_and_empty_sessions_are_removed() -> None:
    manager = ConnectionManager()
    failed = FakeWebSocket(fail=True)
    connected = FakeWebSocket()

    await manager.connect("session-a", failed)
    await manager.publish("session-a", {"type": "assistant_msg", "text": "Hello"})
    assert "session-a" not in manager._connections

    await manager.connect("session-b", connected)
    await manager.disconnect("session-b", connected)
    assert "session-b" not in manager._connections
