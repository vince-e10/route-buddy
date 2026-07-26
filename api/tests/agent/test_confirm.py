import asyncio
import inspect
from pathlib import Path

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.deps
import app.registry
from app.agent.rate_limit import RateLimiter
from app.providers.uber import ProviderError
from app.routers import confirm

from .conftest import RaisingPublisher, StubGeocoder, make_pending, make_session, make_trip


@pytest.fixture
def client(monkeypatch, repos, provider, publisher, config):
    monkeypatch.setattr(app.deps, "session_repo", repos[0])
    monkeypatch.setattr(app.deps, "trip_repo", repos[1])
    monkeypatch.setattr(app.deps, "action_log_repo", repos[2])
    monkeypatch.setattr(app.deps, "pending_repo", repos[3])
    monkeypatch.setattr(app.deps, "provider", provider)
    monkeypatch.setattr(app.deps, "settings", config)
    monkeypatch.setattr(confirm, "_limiter", RateLimiter(10, 60))
    app.registry.set_publisher(publisher)
    application = FastAPI()
    application.include_router(confirm.router)
    return TestClient(application)


@pytest.mark.asyncio
async def test_confirm_executes_book_with_frozen_quote_and_persists_message(
    client, repos, provider, publisher, config
):
    session = make_session("session-1")
    await repos[0].put(session)
    action = make_pending(session.session_id)
    await repos[3].put(action)
    response = client.post("/confirm", json={"token": action.token, "decision": "confirm"})
    assert response.json() == {"result": "executed", "trip_id": "uber:req-booked"}
    quote, guest = provider.book_calls[0]
    assert quote.fare_id == action.payload["quote"]["fare_id"]
    assert guest.phone_number == config.rider_phone
    stored = await repos[1].get("uber:req-booked")
    assert stored.status.value == "processing"
    persisted = await repos[0].get(session.session_id)
    assert persisted.messages[-1]["content"].endswith("status processing")
    serialized = str(persisted.messages) + str(publisher.messages)
    assert config.rider_phone not in serialized
    assert _phases(session.session_id) == ["verified", "executed", "outcome"]


@pytest.mark.asyncio
async def test_confirm_is_single_use_and_double_submit_calls_provider_once(
    client, repos, provider
):
    action = make_pending("session-1")
    await repos[3].put(action)
    responses = await asyncio.gather(
        asyncio.to_thread(
            client.post, "/confirm", json={"token": action.token, "decision": "confirm"}
        ),
        asyncio.to_thread(
            client.post, "/confirm", json={"token": action.token, "decision": "confirm"}
        ),
    )
    assert sorted(response.json()["result"] for response in responses) == ["executed", "expired"]
    assert len(provider.book_calls) == 1


@pytest.mark.asyncio
async def test_dismiss_and_expired_never_call_provider(client, repos, provider, publisher):
    action = make_pending("session-1")
    await repos[3].put(action)
    assert client.post(
        "/confirm", json={"token": action.token, "decision": "dismiss"}
    ).json() == {"result": "dismissed", "trip_id": None}
    assert _phases(action.session_id) == ["outcome"]
    expired = make_pending("session-1", expired=True)
    await repos[3].put(expired)
    assert client.post(
        "/confirm", json={"token": expired.token, "decision": "confirm"}
    ).json() == {"result": "expired", "trip_id": None}
    assert not provider.book_calls


@pytest.mark.asyncio
async def test_provider_failure_reports_failed(client, repos, provider):
    provider.failure = ProviderError("fare_expired", 410, "expired")
    action = make_pending("session-1")
    await repos[3].put(action)
    assert client.post(
        "/confirm", json={"token": action.token, "decision": "confirm"}
    ).json() == {"result": "failed", "trip_id": None}
    rows = boto3.resource("dynamodb").Table("action_log").scan()["Items"]
    assert any(row["payload"].get("code") == "fare_expired" for row in rows)


@pytest.mark.asyncio
async def test_confirm_cancel_uses_provider_state_from_processing(client, repos, provider):
    trip = make_trip("session-1")
    await repos[1].put(trip)
    action = make_pending(
        trip.session_id,
        action_type="cancel",
        payload={"trip_id": trip.trip_id},
    )
    await repos[3].put(action)
    response = client.post("/confirm", json={"token": action.token, "decision": "confirm"})
    assert response.json() == {"result": "executed", "trip_id": trip.trip_id}
    stored = await repos[1].get(trip.trip_id)
    assert stored.status.value == "rider_canceled"
    assert provider.cancel_calls == [trip.provider_request_id]
    assert _phases(action.session_id) == ["verified", "executed", "outcome"]


@pytest.mark.asyncio
async def test_rate_limit_happens_before_claim(client, repos, monkeypatch):
    limiter = RateLimiter(1, 60)
    monkeypatch.setattr(confirm, "_limiter", limiter)
    action = make_pending("session-1")
    await repos[3].put(action)
    limiter.allow(action.token)
    response = client.post("/confirm", json={"token": action.token, "decision": "confirm"})
    assert response.status_code == 429
    assert await repos[3].claim(action.token) is not None


def test_llm_cannot_execute_provider_writes():
    import app.agent.tools as tools

    assert "provider.book" not in inspect.getsource(tools.handle_book_ride)
    assert "provider.cancel" not in inspect.getsource(tools.handle_cancel_ride)
    app_root = Path(tools.__file__).parents[1]
    book_sites = [
        path
        for path in app_root.rglob("*.py")
        if "provider.book(" in path.read_text()
    ]
    cancel_sites = [
        path
        for path in app_root.rglob("*.py")
        if "provider.cancel(" in path.read_text()
    ]
    assert book_sites == [app_root / "routers" / "confirm.py"]
    assert cancel_sites == [app_root / "routers" / "confirm.py"]


@pytest.mark.asyncio
async def test_agent_and_confirm_session_updates_do_not_overwrite_each_other(
    client, repos, provider, publisher
):
    from app.agent.llm import LLMResponse, ToolCall
    from app.agent.loop import AgentServiceImpl

    class BlockingLLM:
        def __init__(self):
            self.calls = 0
            self.blocked = asyncio.Event()
            self.release = asyncio.Event()

        async def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    text=None,
                    tool_calls=[
                        ToolCall(
                            id="search",
                            name="search_places",
                            arguments='{"query":"changi"}',
                        )
                    ],
                )
            self.blocked.set()
            await self.release.wait()
            return LLMResponse(text="Found it.", tool_calls=[])

    session = make_session("race-session")
    await repos[0].put(session)
    action = make_pending(session.session_id)
    await repos[3].put(action)
    llm = BlockingLLM()
    service = AgentServiceImpl(
        session_repo=repos[0],
        trip_repo=repos[1],
        action_log_repo=repos[2],
        pending_repo=repos[3],
        provider=provider,
        geocoder=StubGeocoder(),
        llm=llm,
        fallback_model="fallback/model",
    )
    agent_task = asyncio.create_task(
        service.handle_user_message(session.session_id, "find changi")
    )
    await llm.blocked.wait()
    confirm_task = asyncio.create_task(
        confirm.confirm(confirm.ConfirmRequest(token=action.token, decision="confirm"))
    )
    for _ in range(100):
        if provider.book_calls:
            break
        await asyncio.sleep(0)
    llm.release.set()
    response = await confirm_task
    await agent_task

    assert response == {"result": "executed", "trip_id": "uber:req-booked"}
    messages = (await repos[0].get(session.session_id)).messages
    assert any(message.get("content") == "Found it." for message in messages)
    assert any(
        (message.get("content") or "").startswith("Booking executed:")
        for message in messages
    )


@pytest.mark.asyncio
async def test_post_execution_publisher_failure_keeps_durable_truth(
    client, repos, provider
):
    app.registry.set_publisher(RaisingPublisher())
    action = make_pending("publisher-session")
    await repos[3].put(action)
    response = client.post(
        "/confirm", json={"token": action.token, "decision": "confirm"}
    )
    assert response.json() == {"result": "executed", "trip_id": "uber:req-booked"}
    assert await repos[1].get("uber:req-booked") is not None
    assert _phases(action.session_id) == ["verified", "executed", "outcome"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "put"])
async def test_post_execution_session_context_failure_keeps_durable_truth(
    client, repos, monkeypatch, method
):
    async def fail(*args):
        raise RuntimeError("session storage down")

    monkeypatch.setattr(repos[0], method, fail)
    action = make_pending(f"session-{method}")
    await repos[3].put(action)
    response = client.post(
        "/confirm", json={"token": action.token, "decision": "confirm"}
    )
    assert response.json() == {"result": "executed", "trip_id": "uber:req-booked"}
    assert await repos[1].get("uber:req-booked") is not None
    assert _phases(action.session_id) == ["verified", "executed", "outcome"]


def _phases(session_id):
    rows = boto3.resource("dynamodb").Table("action_log").query(
        KeyConditionExpression=Key("session_id").eq(session_id)
    )["Items"]
    return [row["phase"] for row in sorted(rows, key=lambda row: row["entry_key"])]
