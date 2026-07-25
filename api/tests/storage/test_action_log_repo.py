import pytest
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from app.storage import ActionLogRepo
from tests.storage.conftest import action_log_entry, session


@pytest.mark.asyncio
async def test_append_writes_ordered_entries_without_a_read(dynamodb) -> None:
    session_id = session().session_id
    repo = ActionLogRepo()

    def no_get(*args, **kwargs):
        raise AssertionError("append must not read")

    repo._table.get_item = no_get
    for entry_key in ("001", "002", "003"):
        await repo.append(action_log_entry(session_id, entry_key))

    items = dynamodb.Table("action_log").query(
        KeyConditionExpression=Key("session_id").eq(session_id)
    )["Items"]

    assert [item["entry_key"] for item in items] == ["001", "002", "003"]
    assert all(
        {"session_id", "entry_key", "correlation_id", "phase", "actor", "tool", "payload", "ts"}
        <= item.keys()
        for item in items
    )


def test_action_log_repo_exposes_only_append() -> None:
    assert [name for name in dir(ActionLogRepo) if not name.startswith("_")] == ["append"]


@pytest.mark.asyncio
async def test_append_rejects_duplicate_non_empty_key_without_overwrite(dynamodb) -> None:
    session_id = session().session_id
    repo = ActionLogRepo()
    original = action_log_entry(session_id, "duplicate")
    replacement = action_log_entry(session_id, "duplicate")
    await repo.append(original)

    with pytest.raises(ClientError):
        await repo.append(replacement)

    stored = dynamodb.Table("action_log").get_item(
        Key={"session_id": session_id, "entry_key": "duplicate"}
    )["Item"]
    assert stored["correlation_id"] == original.correlation_id
