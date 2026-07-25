from typing import Protocol


class WsPublisher(Protocol):
    async def publish(self, session_id: str, message: dict) -> None: ...
