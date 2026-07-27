import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.config import settings
from app.models import ActionLogEntry

from ._dynamo import _table, _to_ddb


class ActionLogRepo:
    def __init__(self) -> None:
        self._table = _table(settings.action_log_table)

    async def append(self, entry: ActionLogEntry) -> None:
        value = entry.model_copy(deep=True)
        if not value.entry_key:
            value.entry_key = f"{datetime.now(timezone.utc).isoformat()}#{uuid4().hex[:6]}"
        await asyncio.to_thread(
            self._table.put_item,
            Item=_to_ddb(value.model_dump(mode="json")),
            ConditionExpression="attribute_not_exists(session_id) AND attribute_not_exists(entry_key)",
        )
