import logging
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.models import Driver, LEGAL_TRANSITIONS, Trip, TripStatus

from ._dynamo import _from_ddb, _table, _to_ddb

logger = logging.getLogger(__name__)


class TripRepo:
    def __init__(self) -> None:
        self._table = _table("trips")

    async def put(self, trip: Trip) -> None:
        self._table.put_item(Item=_to_ddb(trip.model_dump(mode="json")))

    async def get(self, trip_id: str) -> Trip | None:
        item = self._table.get_item(Key={"trip_id": trip_id}).get("Item")
        return Trip.model_validate(_from_ddb(item)) if item else None

    async def list_by_session(self, session_id: str) -> list[Trip]:
        items = []
        query = {
            "IndexName": "by_session",
            "KeyConditionExpression": Key("session_id").eq(session_id),
        }
        while True:
            response = self._table.query(**query)
            items.extend(response.get("Items", []))
            key = response.get("LastEvaluatedKey")
            if not key:
                break
            query["ExclusiveStartKey"] = key
        return sorted(
            (Trip.model_validate(_from_ddb(item)) for item in items),
            key=lambda trip: trip.created_at,
        )

    async def apply_status_event(
        self,
        trip_id: str,
        event_id: str,
        new_status: TripStatus,
        driver: Driver | None,
    ) -> Trip | None:
        trip = await self.get(trip_id)
        if trip is None:
            logger.warning("trip status event ignored: trip_id=%s outcome=unknown", trip_id)
            return None
        # ponytail: read-then-check transition, single-writer webhook path; move check into the condition expression if providers ever race
        if new_status not in LEGAL_TRANSITIONS[trip.status]:
            logger.warning("trip status event ignored: trip_id=%s outcome=illegal", trip_id)
            return None

        values = {
            ":status": new_status.value,
            ":eid": event_id,
            ":updated_at": datetime.now(timezone.utc).isoformat(),
        }
        update = "SET #status = :status, last_event_id = :eid, updated_at = :updated_at"
        if driver is not None:
            update += ", driver = :driver"
            values[":driver"] = driver.model_dump(mode="json")
        try:
            response = self._table.update_item(
                Key={"trip_id": trip_id},
                UpdateExpression=update,
                ConditionExpression="attribute_exists(trip_id) AND (attribute_not_exists(last_event_id) OR last_event_id <> :eid)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues=_to_ddb(values),
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        return Trip.model_validate(_from_ddb(response["Attributes"]))
