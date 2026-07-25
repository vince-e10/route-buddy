import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import registry
from app.ws.manager import ConnectionManager


router = APIRouter()
manager = ConnectionManager()
_SESSION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@router.on_event("startup")
async def register_publisher() -> None:
    registry.set_publisher(manager)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    session_id = ws.query_params.get("session_id", "")
    if _SESSION_ID.fullmatch(session_id) is None:
        await ws.close(code=4400)
        return

    await ws.accept()
    await manager.connect(session_id, ws)
    try:
        while True:
            try:
                message = await ws.receive_json()
            except WebSocketDisconnect:
                break
            except Exception:
                await ws.send_json({"type": "error", "message": "invalid message"})
                continue

            if not (
                isinstance(message, dict)
                and message.keys() == {"type", "text"}
                and message["type"] == "user_msg"
                and isinstance(message["text"], str)
                and 0 < len(message["text"]) <= 2000
            ):
                await ws.send_json({"type": "error", "message": "invalid message"})
                continue

            try:
                agent_service = registry.get_agent_service()
            except RuntimeError:
                await ws.send_json({"type": "error", "message": "assistant not available"})
                continue
            await agent_service.handle_user_message(session_id, message["text"])
    finally:
        await manager.disconnect(session_id, ws)
