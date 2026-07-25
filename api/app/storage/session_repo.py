import asyncio
from datetime import datetime, timezone

from app.models import Session

from ._dynamo import _from_ddb, _table, _to_ddb


class SessionRepo:
    def __init__(self) -> None:
        self._table = _table("sessions")

    async def get(self, session_id: str) -> Session | None:
        response = await asyncio.to_thread(
            self._table.get_item,
            Key={"session_id": session_id},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        value = _from_ddb(item)
        if value["expires_at"] <= int(datetime.now(timezone.utc).timestamp()):
            return None
        return Session.model_validate(value)

    async def put(self, session: Session) -> None:
        now = datetime.now(timezone.utc)
        value = session.model_copy(deep=True)
        value.updated_at = now
        value.expires_at = int(now.timestamp()) + 86400
        value.messages = value.messages[-40:]
        value.places = dict(list(value.places.items())[-20:])
        await asyncio.to_thread(
            self._table.put_item, Item=_to_ddb(value.model_dump(mode="json"))
        )
