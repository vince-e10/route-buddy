from datetime import datetime, timedelta, timezone

import pytest

from app.storage import SessionRepo
from tests.storage.conftest import place, quote, session


@pytest.mark.asyncio
async def test_roundtrip() -> None:
    original = session()
    original.quotes = {"quote": quote()}
    original.places = {"place": place(1)}

    repo = SessionRepo()
    await repo.put(original)

    loaded = await repo.get(original.session_id)

    assert loaded is not None
    assert loaded.quotes == original.quotes
    assert loaded.places == original.places
    assert loaded.updated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_absent_returns_none() -> None:
    assert await SessionRepo().get("missing-session") is None


@pytest.mark.asyncio
async def test_code_expiry(dynamodb) -> None:
    original = session()
    repo = SessionRepo()
    await repo.put(original)
    dynamodb.Table("sessions").update_item(
        Key={"session_id": original.session_id},
        UpdateExpression="SET expires_at = :expired",
        ExpressionAttributeValues={":expired": 1},
    )

    assert await repo.get(original.session_id) is None


@pytest.mark.asyncio
async def test_message_cap() -> None:
    original = session()
    original.messages = [{"index": index} for index in range(45)]

    await SessionRepo().put(original)

    loaded = await SessionRepo().get(original.session_id)

    assert loaded is not None
    assert loaded.messages == [{"index": index} for index in range(5, 45)]


@pytest.mark.asyncio
async def test_places_cap() -> None:
    original = session()
    original.places = {f"place-{index}": place(index) for index in range(25)}

    await SessionRepo().put(original)

    loaded = await SessionRepo().get(original.session_id)

    assert loaded is not None
    assert list(loaded.places) == [f"place-{index}" for index in range(5, 25)]
