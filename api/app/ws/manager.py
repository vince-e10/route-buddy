import asyncio

from fastapi import WebSocket


# ponytail: in-process connection registry, single instance; needs a pub/sub bus (SNS/redis) if api ever scales out
class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(session_id, set()).add(ws)

    async def disconnect(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            sockets = self._connections.get(session_id)
            if sockets is None:
                return
            sockets.discard(ws)
            if not sockets:
                del self._connections[session_id]

    async def publish(self, session_id: str, message: dict) -> None:
        async with self._lock:
            sockets = tuple(self._connections.get(session_id, ()))
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                await self.disconnect(session_id, ws)
