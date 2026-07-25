import pytest
import boto3
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.deps
import app.registry
from app.models import Driver, ProviderTripState, TripStatus
from app.providers.uber import ProviderError
from app.routers import webhooks

from .conftest import make_trip


def payload(event_id="evt-1", request_id="req-1", status="accepted"):
    return {
        "event_id": event_id,
        "event_time": 1753430000,
        "event_type": "guests.trips.status_changed",
        "resource_href": f"http://mock/v1/guests/trips/{request_id}",
        "meta": {
            "user_id": "mock-user",
            "org_uuid": "org",
            "resource_id": request_id,
            "status": status,
        },
    }


@pytest.fixture
def client(monkeypatch, repos, provider, publisher, config):
    monkeypatch.setattr(app.deps, "trip_repo", repos[1])
    monkeypatch.setattr(app.deps, "action_log_repo", repos[2])
    monkeypatch.setattr(app.deps, "provider", provider)
    monkeypatch.setattr(app.deps, "settings", config)
    app.registry.set_publisher(publisher)
    application = FastAPI()
    application.include_router(webhooks.router)
    return TestClient(application)


def post(client, body, secret="webhook-secret"):
    return client.post("/webhooks/uber", json=body, headers={"X-Webhook-Secret": secret})


def test_bad_secret_401_and_missing_config_503(client, monkeypatch, config):
    assert post(client, payload(), "wrong").status_code == 401
    monkeypatch.setattr(app.deps, "settings", __import__("dataclasses").replace(config, webhook_shared_secret=""))
    assert post(client, payload()).status_code == 503


@pytest.mark.asyncio
async def test_happy_event_applies_enriches_and_publishes(client, repos, provider, publisher):
    await repos[1].put(make_trip("session-1"))
    provider.get_trip = lambda request_id: _state(request_id)
    assert post(client, payload()).status_code == 204
    stored = await repos[1].get("uber:req-1")
    assert stored.status == TripStatus.accepted
    assert stored.driver.name == "Driver"
    assert publisher.messages[-1][0] == "session-1"
    assert publisher.messages[-1][1]["type"] == "trip_update"
    rows = boto3.resource("dynamodb").Table("action_log").scan()["Items"]
    assert rows[0]["payload"]["applied"] is True
    assert rows[0]["correlation_id"].startswith("act_")


async def _state(request_id):
    return ProviderTripState(
        provider_request_id=request_id,
        status=TripStatus.accepted,
        driver=Driver(name="Driver", rating=4.8),
    )


@pytest.mark.asyncio
async def test_duplicate_unknown_and_illegal_events_are_204_without_extra_publish(
    client, repos, publisher
):
    assert post(client, payload(request_id="missing")).status_code == 204
    assert publisher.messages == []
    await repos[1].put(make_trip("session-1"))
    assert post(client, payload()).status_code == 204
    count = len(publisher.messages)
    assert post(client, payload()).status_code == 204
    assert len(publisher.messages) == count
    rows = boto3.resource("dynamodb").Table("action_log").scan()["Items"]
    assert any(row["payload"]["applied"] is False for row in rows)
    await repos[1].put(make_trip("session-2", status=TripStatus.completed, request_id="done"))
    assert post(client, payload(request_id="done")).status_code == 204
    assert len(publisher.messages) == count


@pytest.mark.asyncio
async def test_driver_enrichment_failure_is_best_effort(
    client, repos, provider, publisher
):
    await repos[1].put(make_trip("session-1"))
    provider.get_trip_failure = ProviderError("unreachable", 503, "down")
    assert post(client, payload()).status_code == 204
    assert (await repos[1].get("uber:req-1")).status == TripStatus.accepted
    assert publisher.messages[-1][1]["status"] == "accepted"


@pytest.mark.asyncio
async def test_driver_enrichment_unexpected_failure_is_best_effort(
    client, repos, provider, publisher
):
    async def fail(request_id):
        raise ValueError("malformed provider response")

    await repos[1].put(make_trip("session-1"))
    provider.get_trip = fail
    assert post(client, payload()).status_code == 204
    stored = await repos[1].get("uber:req-1")
    assert stored.status == TripStatus.accepted
    assert stored.driver is None
    assert publisher.messages[-1][1]["status"] == "accepted"
