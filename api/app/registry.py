from __future__ import annotations

from typing import TYPE_CHECKING

from app.ws.publisher import WsPublisher

if TYPE_CHECKING:
    from app.agent.service import AgentService


class NoopPublisher:
    async def publish(self, session_id: str, message: dict) -> None:
        return None


_publisher: WsPublisher = NoopPublisher()
_agent_service: AgentService | None = None


def set_publisher(p: WsPublisher) -> None:
    global _publisher
    _publisher = p


def get_publisher() -> WsPublisher:
    return _publisher


def set_agent_service(s: AgentService) -> None:
    global _agent_service
    _agent_service = s


def get_agent_service() -> AgentService:
    if _agent_service is None:
        raise RuntimeError("agent service not wired")
    return _agent_service
