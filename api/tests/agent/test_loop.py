import json
from dataclasses import replace

import boto3
import pytest
from boto3.dynamodb.conditions import Key

from app.agent.llm import LLMError, LLMResponse, ToolCall
from app.agent.loop import AgentServiceImpl
from app.config import settings
from app.models import LatLng, Place
from app.providers.uber import ProviderError
from app.registry import set_publisher

from .conftest import RaisingPublisher, StubGeocoder, make_quote, make_session, make_trip


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools, *, model=None):
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def service(repos, provider, publisher, llm):
    set_publisher(publisher)
    return AgentServiceImpl(
        session_repo=repos[0],
        trip_repo=repos[1],
        action_log_repo=repos[2],
        pending_repo=repos[3],
        provider=provider,
        geocoder=StubGeocoder(),
        llm=llm,
        fallback_model="fallback/model",
    )


@pytest.mark.asyncio
async def test_read_tool_roundtrip(repos, provider, publisher):
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="c1", name="search_places", arguments='{"query":"changi"}')
                ],
            ),
            LLMResponse(text="Found it.", tool_calls=[]),
        ]
    )
    await service(repos, provider, publisher, llm).handle_user_message("session-1", "find changi")
    persisted = await repos[0].get("session-1")
    assert len(persisted.messages) == 4
    assert json.loads(llm.calls[1]["messages"][-1]["content"])["places"]
    assert publisher.messages[-1] == (
        "session-1",
        {"type": "assistant_msg", "text": "Found it."},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (ToolCall(id="bad", name="search_places", arguments='{"query":'), "malformed_arguments"),
        (ToolCall(id="bad", name="destroy_world", arguments="{}"), "unknown_tool"),
        (ToolCall(id="bad", name="book_ride", arguments='{"fare_id":"x"}'), "unknown_tool"),
        (ToolCall(id="bad", name="search_places", arguments="{}"), "invalid_arguments"),
    ],
)
async def test_invalid_tool_calls_are_refused_and_loop_continues(
    repos, provider, publisher, call, expected
):
    llm = ScriptedLLM(
        [
            LLMResponse(text=None, tool_calls=[call]),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )
    await service(repos, provider, publisher, llm).handle_user_message("session-1", "x")
    assert "error" in json.loads(llm.calls[1]["messages"][-1]["content"])
    assert [item["model"] for item in llm.calls] == [None, "fallback/model"]
    rows = boto3.resource("dynamodb").Table("action_log").scan()["Items"]
    assert any(row["payload"].get("error") == expected for row in rows)


@pytest.mark.asyncio
async def test_empty_session_exposes_only_always_available_tools(
    repos, provider, publisher
):
    llm = ScriptedLLM([LLMResponse(text="Hello.", tool_calls=[])])

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "hi")

    assert _tool_names(llm.calls[0]) == {"search_places", "list_session_trips"}


@pytest.mark.asyncio
async def test_each_request_uses_current_place_quote_and_trip_state(
    repos, provider, publisher
):
    session = make_session("session-1")
    session.places = {
        place_id: Place(
            place_id=place_id,
            name=place_id,
            address=place_id,
            postal="123456",
            location=LatLng(lat=1.3, lng=103.8),
        )
        for place_id in ("pickup", "dropoff")
    }
    await repos[0].put(session)
    trip = make_trip(session.session_id)
    await repos[1].put(trip)
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="quote",
                        name="get_quotes",
                        arguments='{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
                    )
                ],
            ),
            LLMResponse(text="Quoted.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message(
        session.session_id, "quote"
    )

    first = _schemas_by_name(llm.calls[0])
    second = _schemas_by_name(llm.calls[1])
    assert set(first) == {
        "search_places",
        "get_quotes",
        "get_trip_status",
        "list_session_trips",
        "cancel_ride",
    }
    assert first["get_quotes"]["pickup_place_id"]["enum"] == ["pickup", "dropoff"]
    assert first["get_quotes"]["dropoff_place_id"]["enum"] == ["pickup", "dropoff"]
    assert first["get_trip_status"]["trip_id"]["enum"] == [trip.trip_id]
    assert first["cancel_ride"]["trip_id"]["enum"] == [trip.trip_id]
    assert "book_ride" not in first
    assert second["book_ride"]["fare_id"]["enum"] == ["fare-1"]


@pytest.mark.asyncio
async def test_each_llm_request_takes_one_trip_snapshot(
    repos, provider, publisher, monkeypatch
):
    calls = 0
    original = repos[1].list_by_session

    async def count(session_id):
        nonlocal calls
        calls += 1
        return await original(session_id)

    monkeypatch.setattr(repos[1], "list_by_session", count)
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="search", name="search_places", arguments='{"query":"x"}')
                ],
            ),
            LLMResponse(text="Found.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "find")

    assert calls == len(llm.calls) == 2


@pytest.mark.asyncio
async def test_trip_snapshot_failure_skips_llm_and_publishes_availability_error(
    repos, provider, publisher, monkeypatch
):
    async def fail(session_id):
        raise RuntimeError("storage down")

    monkeypatch.setattr(repos[1], "list_by_session", fail)
    llm = ScriptedLLM([LLMResponse(text="must not run", tool_calls=[])])

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "hi")

    assert llm.calls == []
    assert publisher.messages[-1] == (
        "session-1",
        {
            "type": "error",
            "message": "The assistant is unavailable right now, try again shortly.",
        },
    )


@pytest.mark.asyncio
async def test_invalid_supplied_enum_pins_fallback(repos, provider, publisher):
    await repos[0].put(_route_session("session-1"))
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="bad-enum",
                        name="get_quotes",
                        arguments='{"pickup_place_id":"invented","dropoff_place_id":"dropoff"}',
                    )
                ],
            ),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "x")

    assert [item["model"] for item in llm.calls] == [None, "fallback/model"]
    assert provider.quote_calls == 0


@pytest.mark.asyncio
async def test_valid_primary_requests_never_pin_a_model(repos, provider, publisher):
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="search", name="search_places", arguments='{"query":"x"}')
                ],
            ),
            LLMResponse(text="Found.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "find")

    assert [item["model"] for item in llm.calls] == [None, None]


@pytest.mark.asyncio
async def test_domain_error_does_not_pin_fallback(repos, provider, publisher):
    await repos[0].put(_route_session("session-1"))
    provider.quote_failure = ProviderError("unavailable", 503, "provider down")
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="quote",
                        name="get_quotes",
                        arguments='{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
                    )
                ],
            ),
            LLMResponse(text="Try later.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "quote")

    assert [item["model"] for item in llm.calls] == [None, None]


@pytest.mark.asyncio
async def test_second_structural_rejection_stops_with_safe_reask(
    repos, provider, publisher
):
    invalid = LLMResponse(
        text=None,
        tool_calls=[ToolCall(id="bad", name="search_places", arguments="{")],
    )
    llm = ScriptedLLM([invalid, invalid, LLMResponse(text="must not run", tool_calls=[])])

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "x")

    assert [item["model"] for item in llm.calls] == [None, "fallback/model"]
    assert publisher.messages[-1][1]["text"] == "Sorry, I got stuck - could you rephrase?"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_text", [None, ""])
async def test_empty_fallback_response_stops_with_one_safe_reask(
    repos, provider, publisher, fallback_text
):
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[ToolCall(id="bad", name="search_places", arguments="{")],
            ),
            LLMResponse(text=fallback_text, tool_calls=[]),
            LLMResponse(text="must not run", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "x")

    assert [item["model"] for item in llm.calls] == [None, "fallback/model"]
    assert publisher.messages == [
        (
            "session-1",
            {
                "type": "assistant_msg",
                "text": "Sorry, I got stuck - could you rephrase?",
            },
        )
    ]


@pytest.mark.asyncio
async def test_valid_fallback_tool_returns_later_request_to_primary(
    repos, provider, publisher
):
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[ToolCall(id="bad", name="search_places", arguments="{")],
            ),
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="valid", name="search_places", arguments='{"query":"x"}')
                ],
            ),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "x")

    assert [item["model"] for item in llm.calls] == [None, "fallback/model", None]
    assert "places" in json.loads(llm.calls[2]["messages"][-1]["content"])


@pytest.mark.asyncio
async def test_multiple_tool_calls_are_all_rejected_before_write_dispatch(
    repos, provider, publisher
):
    session = _route_session("session-1")
    session.quotes = {"fare-1": make_quote()}
    await repos[0].put(session)
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(
                        id="book-one",
                        name="book_ride",
                        arguments='{"fare_id":"fare-1"}',
                    ),
                    ToolCall(
                        id="book-two",
                        name="book_ride",
                        arguments='{"fare_id":"fare-1"}',
                    ),
                ],
            ),
            LLMResponse(text="Please choose one.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("session-1", "book")

    assert [item["model"] for item in llm.calls] == [None, "fallback/model"]
    assert boto3.resource("dynamodb").Table("pending_actions").scan()["Items"] == []
    tool_messages = [
        message
        for message in (await repos[0].get("session-1")).messages
        if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == [
        "book-one",
        "book-two",
    ]
    assert all("error" in json.loads(message["content"]) for message in tool_messages)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_calls", "expected_code"),
    [
        (
            [
                ToolCall(
                    id="malformed",
                    name="search_places",
                    arguments='{"query":"' + "sentinel-" * 80,
                )
            ],
            "malformed_arguments",
        ),
        ([ToolCall(id="unknown", name="destroy_world", arguments="{}")], "unknown_tool"),
        (
            [ToolCall(id="invalid", name="search_places", arguments="{}")],
            "invalid_arguments",
        ),
        (
            [
                ToolCall(id="one", name="search_places", arguments='{"query":"one"}'),
                ToolCall(id="two", name="search_places", arguments='{"query":"two"}'),
            ],
            "multiple_tool_calls",
        ),
    ],
)
async def test_structural_rejections_write_one_bounded_requested_verified_pair(
    repos, provider, publisher, tool_calls, expected_code
):
    llm = ScriptedLLM(
        [
            LLMResponse(text=None, tool_calls=tool_calls),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message("audit", "x")

    rows = _action_rows("audit")
    assert [(row["phase"], row["actor"]) for row in rows] == [
        ("requested", "llm"),
        ("verified", "system"),
    ]
    assert len({row["correlation_id"] for row in rows}) == 1
    assert rows[0]["payload"]["proposals"] == [
        {"name": call.name, "arguments": call.arguments[:512]} for call in tool_calls
    ]
    assert rows[1]["payload"]["error"] == expected_code
    assert all(
        len(proposal["arguments"]) <= 512
        for proposal in rows[0]["payload"]["proposals"]
    )
    if expected_code == "multiple_tool_calls":
        assert (
            boto3.resource("dynamodb").Table("pending_actions").scan()["Items"]
            == []
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "sensitive"),
    [
        ('{"query":"call +6591234567","extra":true}', "+6591234567"),
        ('{"query":"mail rider@example.com","extra":true}', "rider@example.com"),
        (
            '{"query":"configured-secret-sentinel","extra":true}',
            "configured-secret-sentinel",
        ),
        (
            '{"query":"x","x-api-key":"opaque-credential-sentinel"}',
            "opaque-credential-sentinel",
        ),
        (
            (
                '{"query":"x","headers":{"nested":{"x":"safe"},'
                '"x-custom":"header-sentinel"}}'
            ),
            "header-sentinel",
        ),
        (
            '{"query":"x","confirmation_token":"confirmation-token-sentinel"}',
            "confirmation-token-sentinel",
        ),
    ],
)
async def test_invalid_audit_redacts_sensitive_arguments(
    repos, provider, publisher, monkeypatch, arguments, sensitive
):
    monkeypatch.setattr(
        "app.agent.loop.settings",
        replace(
            settings,
            openrouter_api_key="",
            uber_api_token="configured-secret-sentinel",
        ),
        raising=False,
    )
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="invalid", name="search_places", arguments=arguments)
                ],
            ),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message(
        "audit-redaction", "x"
    )

    persisted = _action_rows("audit-redaction")[0]["payload"]["proposals"][0][
        "arguments"
    ]
    assert sensitive not in persisted
    assert "[REDACTED]" in persisted
    assert persisted.startswith('{"query"')


@pytest.mark.asyncio
async def test_invalid_audit_redacts_opaque_aws_access_key_before_cap(
    repos, provider, publisher
):
    opaque = "opaque-access-credential"
    arguments = (
        f'{{"aws_secret_access_key":"{opaque}","query":"' + "x" * 600 + '"}'
    )
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="invalid", name="search_places", arguments=arguments)
                ],
            ),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message(
        "audit-access-key", "x"
    )

    persisted = _action_rows("audit-access-key")[0]["payload"]["proposals"][0][
        "arguments"
    ]
    assert opaque not in persisted
    assert persisted.startswith('{"aws_secret_access_key":"[REDACTED]"')
    assert len(persisted) <= 512


@pytest.mark.asyncio
async def test_invalid_audit_redacts_before_final_length_cap(
    repos, provider, publisher
):
    arguments = '{"query":"91234567 ' + "x" * 600
    llm = ScriptedLLM(
        [
            LLMResponse(
                text=None,
                tool_calls=[
                    ToolCall(id="malformed", name="search_places", arguments=arguments)
                ],
            ),
            LLMResponse(text="Recovered.", tool_calls=[]),
        ]
    )

    await service(repos, provider, publisher, llm).handle_user_message(
        "audit-cap", "x"
    )

    persisted = _action_rows("audit-cap")[0]["payload"]["proposals"][0]["arguments"]
    assert persisted.startswith('{"query":"[REDACTED] ')
    assert "91234567" not in persisted
    assert len(persisted) == 512


@pytest.mark.asyncio
async def test_iteration_cap(repos, provider, publisher):
    calls = [
        LLMResponse(
            text=None,
            tool_calls=[ToolCall(id=f"c{i}", name="list_session_trips", arguments="{}")],
        )
        for i in range(7)
    ]
    llm = ScriptedLLM(calls)
    await service(repos, provider, publisher, llm).handle_user_message("session-1", "loop")
    assert len(llm.calls) == 6
    assert publisher.messages[-1][1]["text"] == "Sorry, I got stuck - could you rephrase?"


@pytest.mark.asyncio
async def test_rate_limit(repos, provider, publisher):
    llm = ScriptedLLM([LLMResponse(text="ok", tool_calls=[])] * 20)
    svc = service(repos, provider, publisher, llm)
    for _ in range(21):
        await svc.handle_user_message("session-1", "hi")
    assert len(llm.calls) == 20
    assert publisher.messages[-1][1] == {
        "type": "error",
        "message": "You're sending messages too quickly, give me a moment.",
    }


@pytest.mark.asyncio
async def test_llm_error_publishes_friendly_error_and_persists(repos, provider, publisher):
    llm = ScriptedLLM([LLMError("boom")])
    await service(repos, provider, publisher, llm).handle_user_message("session-1", "hi")
    assert publisher.messages[-1][1]["message"].startswith("The assistant is unavailable")
    assert (await repos[0].get("session-1")).messages == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "put"])
async def test_storage_failure_never_raises_to_websocket_caller(
    repos, provider, publisher, monkeypatch, method
):
    llm = ScriptedLLM([LLMResponse(text="ok", tool_calls=[])])

    async def fail_put(session):
        raise RuntimeError("storage down")

    monkeypatch.setattr(repos[0], method, fail_put)
    await service(repos, provider, publisher, llm).handle_user_message("session-1", "hi")


@pytest.mark.asyncio
async def test_raising_publisher_never_breaks_persistence_or_rate_limit(
    repos, provider
):
    llm = ScriptedLLM([LLMResponse(text="ok", tool_calls=[])] * 20)
    svc = service(repos, provider, RaisingPublisher(), llm)
    for _ in range(21):
        await svc.handle_user_message("publisher-failure", "hi")
    assert len(llm.calls) == 20
    assert (await repos[0].get("publisher-failure")).messages


def _schemas_by_name(call):
    return {
        tool["function"]["name"]: tool["function"]["parameters"]["properties"]
        for tool in call["tools"]
    }


def _tool_names(call):
    return set(_schemas_by_name(call))


def _action_rows(session_id):
    rows = boto3.resource("dynamodb").Table("action_log").query(
        KeyConditionExpression=Key("session_id").eq(session_id)
    )["Items"]
    return sorted(rows, key=lambda row: row["entry_key"])


def _route_session(session_id):
    session = make_session(session_id)
    session.places = {
        place_id: Place(
            place_id=place_id,
            name=place_id,
            address=place_id,
            postal="123456",
            location=LatLng(lat=1.3, lng=103.8),
        )
        for place_id in ("pickup", "dropoff")
    }
    return session
