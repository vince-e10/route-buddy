import asyncio
import importlib

import pytest

import app.registry as registry


def reset_registry():
    return importlib.reload(registry)


def test_default_publisher_is_noop() -> None:
    current = reset_registry()

    asyncio.run(current.get_publisher().publish("x", {}))


def test_default_agent_service_raises() -> None:
    current = reset_registry()

    with pytest.raises(RuntimeError, match="agent service not wired"):
        current.get_agent_service()


def test_set_then_get_roundtrip() -> None:
    current = reset_registry()

    class Publisher:
        async def publish(self, session_id: str, message: dict) -> None:
            return None

    class AgentService:
        async def handle_user_message(self, session_id: str, text: str) -> None:
            return None

    publisher = Publisher()
    agent_service = AgentService()
    current.set_publisher(publisher)
    current.set_agent_service(agent_service)

    assert current.get_publisher() is publisher
    assert current.get_agent_service() is agent_service
