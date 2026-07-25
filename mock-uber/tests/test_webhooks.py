import asyncio

import pytest

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
