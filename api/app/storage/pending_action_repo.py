from datetime import datetime, timezone

from botocore.exceptions import ClientError

from app.models import PendingAction

from ._dynamo import _from_ddb, _table, _to_ddb


class PendingActionRepo:
    def __init__(self) -> None:
        self._table = _table("pending_actions")

    async def put(self, action: PendingAction) -> None:
        self._table.put_item(Item=_to_ddb(action.model_dump(mode="json")))

    async def claim(self, token: str) -> PendingAction | None:
        try:
            response = self._table.delete_item(
                Key={"token": token},
                ConditionExpression="attribute_exists(#t)",
                ExpressionAttributeNames={"#t": "token"},
                ReturnValues="ALL_OLD",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        item = response.get("Attributes")
        if item is None:
            return None
        value = _from_ddb(item)
        if value["expires_at"] <= int(datetime.now(timezone.utc).timestamp()):
            return None
        return PendingAction.model_validate(value)
