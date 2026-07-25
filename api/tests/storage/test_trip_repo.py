from datetime import timedelta

import pytest

from app.models import Driver, TripStatus
from app.storage import TripRepo
from app.storage._dynamo import _to_ddb
from tests.storage.conftest import now, session, trip


@pytest.mark.asyncio
async def test_put_get_roundtrip() -> None:
    original = trip(session().session_id)
    repo = TripRepo()
    await repo.put(original)

    assert await repo.get(original.trip_id) == original


@pytest.mark.asyncio
async def test_list_by_session_ordered() -> None:
    session_id = session().session_id
    created = now()
    expected = [
        trip(session_id, created + timedelta(seconds=offset)) for offset in (2, 0, 1)
    ]
    repo = TripRepo()
    for item in expected:
        await repo.put(item)

    loaded = await repo.list_by_session(session_id)

    assert [item.trip_id for item in loaded] == [
        expected[1].trip_id,
        expected[2].trip_id,
        expected[0].trip_id,
    ]


@pytest.mark.asyncio
async def test_apply_event_happy() -> None:
    original = trip(session().session_id)
    repo = TripRepo()
    await repo.put(original)
    driver = Driver(name="Ada", rating=4.8)

    updated = await repo.apply_status_event(
        original.trip_id, "event-1", TripStatus.accepted, driver
    )

    assert updated is not None
    assert updated.status is TripStatus.accepted
    assert updated.last_event_id == "event-1"
    assert updated.driver == driver


@pytest.mark.asyncio
async def test_apply_event_duplicate() -> None:
    original = trip(session().session_id)
    repo = TripRepo()
    await repo.put(original)
    first = await repo.apply_status_event(
        original.trip_id, "event-1", TripStatus.accepted, None
    )

    duplicate = await repo.apply_status_event(
        original.trip_id, "event-1", TripStatus.arriving, None
    )

    assert first is not None
    assert duplicate is None
    assert (await repo.get(original.trip_id)).status is TripStatus.accepted


@pytest.mark.asyncio
async def test_apply_event_illegal_transition() -> None:
    original = trip(session().session_id)
    original.status = TripStatus.completed
    repo = TripRepo()
    await repo.put(original)

    assert (
        await repo.apply_status_event(
            original.trip_id, "event-1", TripStatus.accepted, None
        )
        is None
    )


@pytest.mark.asyncio
async def test_apply_event_unknown_trip() -> None:
    assert (
        await TripRepo().apply_status_event(
            "unknown-trip", "event-1", TripStatus.accepted, None
        )
        is None
    )


class _PagedTable:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.calls: list[dict] = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages.pop(0)


@pytest.mark.asyncio
async def test_list_by_session_consumes_every_page_before_sorting() -> None:
    session_id = session().session_id
    first = trip(session_id, now() + timedelta(seconds=2))
    second = trip(session_id, now())
    fake = _PagedTable(
        [
            {
                "Items": [_to_ddb(first.model_dump(mode="json"))],
                "LastEvaluatedKey": {"trip_id": first.trip_id},
            },
            {"Items": [_to_ddb(second.model_dump(mode="json"))]},
        ]
    )
    repo = TripRepo.__new__(TripRepo)
    repo._table = fake

    loaded = await repo.list_by_session(session_id)

    assert [item.trip_id for item in loaded] == [second.trip_id, first.trip_id]
    assert fake.calls[1]["ExclusiveStartKey"] == {"trip_id": first.trip_id}
