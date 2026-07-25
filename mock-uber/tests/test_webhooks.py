import asyncio

import pytest

from app.models import TripStatus
from app.sim import Simulator
from app.store import Store


@pytest.mark.asyncio
async def test_webhook_retries_twice_then_succeeds_in_exactly_three_attempts(monkeypatch):
    simulator = Simulator(Store())
    attempts = []

    async def post(_payload):
        attempts.append(1)
        return len(attempts) == 3

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(simulator, "_post_webhook", post)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    await simulator.deliver_webhook({"event_id": "evt_test"})
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_happy_lifecycle_emits_ordered_webhooks_with_driver_and_secret(monkeypatch):
    monkeypatch.setenv("MOCK_DETERMINISTIC", "1")
    monkeypatch.setenv("WEBHOOK_SHARED_SECRET", "test-secret")
    store = Store()
    simulator = Simulator(store)
    delivered = []

    class Response:
        status_code = 200

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, json, headers):
            delivered.append((json, headers, await store.get_trip(json["meta"]["resource_id"])))
            return Response()

    monkeypatch.setattr("app.sim.httpx.AsyncClient", Client)
    fare_id, fare = await store.issue_fare(
        "uberx-sg", 4.0, {"latitude": 1, "longitude": 1}, {"latitude": 2, "longitude": 2}, 1.0
    )
    trip = await store.create_trip(
        "uberx-sg", fare_id, {"latitude": 1, "longitude": 1}, {"latitude": 2, "longitude": 2},
        {"first_name": "Ada", "last_name": "Lovelace", "phone_number": "+6591234567"}, fare.surge_multiplier,
    )
    assert trip.status == TripStatus.processing
    await simulator._run(trip.request_id, trip.scenario)

    assert [item[0]["meta"]["status"] for item in delivered] == ["accepted", "arriving", "in_progress", "completed"]
    assert all(item[2].driver is not None for item in delivered)
    assert len({item[0]["event_id"] for item in delivered}) == 4
    assert all(item[0]["event_id"].startswith("evt_") for item in delivered)
    assert all(item[0]["meta"]["resource_id"] == trip.request_id for item in delivered)
    assert all(item[1]["X-Webhook-Secret"] == "test-secret" for item in delivered)
