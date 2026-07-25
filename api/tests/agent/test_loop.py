import json

import pytest

from app.agent.llm import LLMError, LLMResponse, ToolCall
from app.agent.loop import AgentServiceImpl
from app.registry import set_publisher

from .conftest import RaisingPublisher, StubGeocoder


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, tools):
        self.calls.append(messages)
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
    assert json.loads(llm.calls[1][-1]["content"])["places"]
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
    assert "error" in json.loads(llm.calls[1][-1]["content"])
    rows = __import__("boto3").resource("dynamodb").Table("action_log").scan()["Items"]
    assert any(row["payload"].get("error") == expected for row in rows)


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
