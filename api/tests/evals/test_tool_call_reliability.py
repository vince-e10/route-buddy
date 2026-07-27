import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.llm import LLMError, LLMResponse, LLMUsage, ToolCall
from app.agent.tool_contracts import tool_schemas
from evals.tool_call_reliability import (
    EvaluationReport,
    GoldenCase,
    _main,
    classify,
    load_cases,
    nearest_rank,
    run_evaluation,
)


FIXTURE = Path(__file__).parents[2] / "evals" / "golden-set.json"


def test_generated_tool_schemas_are_exact_and_forbid_extra_properties():
    schemas = {
        schema["function"]["name"]: schema["function"]["parameters"]
        for schema in tool_schemas()
    }

    assert schemas == {
        "search_places": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "get_quotes": {
            "type": "object",
            "properties": {
                "pickup_place_id": {"type": "string"},
                "dropoff_place_id": {"type": "string"},
            },
            "required": ["pickup_place_id", "dropoff_place_id"],
            "additionalProperties": False,
        },
        "get_trip_status": {
            "type": "object",
            "properties": {"trip_id": {"type": "string"}},
            "required": ["trip_id"],
            "additionalProperties": False,
        },
        "list_session_trips": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    }


def call(name: str, arguments: str) -> LLMResponse:
    return LLMResponse(
        text=None,
        tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments)],
    )


def case(**changes) -> GoldenCase:
    values = {
        "id": "case",
        "category": "quote",
        "user_message": "Quote the exact route",
        "preceding_messages": [],
        "tools": [
            "search_places",
            "get_quotes",
            "get_trip_status",
            "list_session_trips",
        ],
        "expected": "tool",
        "expected_tool": "get_quotes",
        "allowed_tools": ["get_quotes"],
        "expected_arguments": {
            "pickup_place_id": "pickup",
            "dropoff_place_id": "dropoff",
        },
        "allowed_values": {
            "pickup_place_id": ["pickup", "other"],
            "dropoff_place_id": ["dropoff"],
        },
        "forbidden_tools": [
            "search_places",
            "get_trip_status",
            "list_session_trips",
        ],
        "ambiguity": False,
        "write_proposal": False,
        "rationale": "The exact place IDs must be reused.",
        "recovery": False,
    }
    values.update(changes)
    return GoldenCase.model_validate(values)


def test_golden_set_migrates_every_case_to_read_only_tools():
    cases = load_cases(FIXTURE)

    assert len(cases) == 34
    assert not any(item.write_proposal for item in cases)
    assert all(
        set(item.tools)
        == {
            "search_places",
            "get_quotes",
            "get_trip_status",
            "list_session_trips",
        }
        for item in cases
    )
    assert all(item.expected_tool not in {"book_ride", "cancel_ride"} for item in cases)
    assert all(item.max_attempts <= 6 for item in cases)
    assert {
        "search-postal-code",
        "search-dropoff-after-pickup",
        "book-ambiguous-it",
        "book-expired-quote",
        "no-session-trips",
        "cancel-completed-trip",
    } <= {item.id for item in cases}
    guidance = {
        item.id
        for item in cases
        if item.rationale.startswith("Typed write intent")
    }
    assert guidance == {
        "book-cheapest",
        "book-named-product",
        "book-bypass-confirmation",
        "book-price-change-new-confirmation",
        "cancel-only-trip",
        "cancel-explicit-trip",
        "cancel-bypass-confirmation",
        "cancel-latest-active",
        "ignore-tool-result-instruction",
        "reject-invented-fare-id",
        "recover-malformed-book-call",
        "unknown-target-ask-before-cancel",
        "book-ambiguous-it",
        "book-expired-quote",
        "cancel-named-product",
        "cancel-completed-trip",
        "recover-malformed-json",
        "recover-unknown-tool",
        "recover-invalid-arguments",
    }
    assert all(
        any("select" in phrase and "card" in phrase for phrase in item.required_text_any)
        and {
            "has been booked",
            "has been canceled",
            "has been cancelled",
            "confirmation request created",
        }
        <= set(item.forbidden_text)
        for item in cases
        if item.id in guidance
    )


def test_legacy_write_calls_are_unknown_even_for_legacy_classifier_values():
    assert classify(case(), call("book_ride", '{"fare_id":"fare_1"}')) == "unknown_tool"


@pytest.mark.parametrize(
    ("response", "changes", "outcome"),
    [
        (call("get_quotes", "{"), {}, "invalid_json"),
        (call("invented", "{}"), {}, "unknown_tool"),
        (
            call(
                "get_quotes",
                '{"pickup_place_id":1,"dropoff_place_id":"dropoff"}',
            ),
            {},
            "schema_mismatch",
        ),
        (
            call(
                "get_quotes",
                '{"pickup_place_id":"made_up","dropoff_place_id":"dropoff"}',
            ),
            {},
            "illegal_id",
        ),
        (call("search_places", '{"query":"pickup"}'), {}, "wrong_tool"),
        (
            call(
                "get_quotes",
                '{"pickup_place_id":"other","dropoff_place_id":"dropoff"}',
            ),
            {},
            "wrong_target",
        ),
        (
            call("search_places", '{"query":"Orchard"}'),
            {
                "expected": "clarify",
                "expected_tool": None,
                "allowed_tools": [],
                "expected_arguments": {},
                "ambiguity": True,
            },
            "should_clarify",
        ),
        (LLMResponse(text="I cannot.", tool_calls=[]), {}, "unnecessary_refusal"),
        (LLMResponse(text=None, tool_calls=[]), {}, "no_response"),
        (
            call(
                "get_quotes",
                '{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
            ),
            {},
            "pass",
        ),
    ],
)
def test_classification_precedence(response, changes, outcome):
    assert classify(case(**changes), response) == outcome


def test_any_bad_parallel_call_fails_with_primary_precedence():
    response = LLMResponse(
        text=None,
        tool_calls=[
            ToolCall(id="one", name="search_places", arguments='{"query":"x"}'),
            ToolCall(id="two", name="get_quotes", arguments="{"),
        ],
    )

    assert classify(case(), response) == "invalid_json"


def test_text_and_clarification_require_declarative_evidence():
    clarification = case(
        expected="clarify",
        expected_tool=None,
        allowed_tools=[],
        expected_arguments={},
        ambiguity=True,
        required_text_any=["which ride"],
        forbidden_text=["has been booked"],
    )

    assert (
        classify(
            clarification,
            LLMResponse(text="Which ride should I use?", tool_calls=[]),
        )
        == "pass"
    )
    assert (
        classify(
            clarification,
            LLMResponse(text="The ride has been booked.", tool_calls=[]),
        )
        == "should_clarify"
    )
    assert (
        classify(
            clarification.model_copy(
                update={"expected": "text", "required_text_any": ["no trips"]}
            ),
            LLMResponse(text="A trip is arriving.", tool_calls=[]),
        )
        == "unnecessary_refusal"
    )


def test_case_omitted_tool_is_unknown_even_when_globally_known():
    response = call("get_trip_status", '{"trip_id":"trip_1"}')

    assert classify(case(tools=["get_quotes"]), response) == "unknown_tool"


def test_nearest_rank_percentiles_are_deterministic():
    assert nearest_rank([1, 2, 3, 4], 0.5) == 2
    assert nearest_rank([1, 2, 3, 4], 0.95) == 4


class ScriptedClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.tools = []

    async def complete(self, messages, tools, *, model=None):
        self.calls += 1
        self.tools.append(tools)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_evaluator_supplies_exact_case_schemas_without_dispatch(monkeypatch, tmp_path):
    client = ScriptedClient(
        [
            call(
                "get_quotes",
                '{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
            )
        ]
    )

    await run_evaluation(
        client=client,
        cases=[
            case(
                category="quote",
                tools=[
                    "search_places",
                    "get_quotes",
                    "get_trip_status",
                    "list_session_trips",
                ],
                expected_tool="get_quotes",
                allowed_tools=["get_quotes"],
                expected_arguments={
                    "pickup_place_id": "pickup",
                    "dropoff_place_id": "dropoff",
                },
                allowed_values={
                    "pickup_place_id": ["pickup"],
                    "dropoff_place_id": ["dropoff"],
                },
                write_proposal=False,
            )
        ],
        models=["provider/model"],
        runs=1,
        output=tmp_path / "report.json",
    )

    assert [
        tool["function"]["name"] for tool in client.tools[0]
    ] == [
        "search_places",
        "get_quotes",
        "get_trip_status",
        "list_session_trips",
    ]


@pytest.mark.asyncio
async def test_recovery_is_bounded_and_never_dispatches(monkeypatch, tmp_path):
    from app.agent import tools as production_tools

    async def fail_if_dispatched(*args, **kwargs):
        raise AssertionError("tool handler was dispatched")

    monkeypatch.setitem(production_tools.HANDLERS, "get_quotes", fail_if_dispatched)
    failing = call(
        "get_quotes",
        '{"pickup_place_id":"invented","dropoff_place_id":"dropoff"}',
    )
    passing = call(
        "get_quotes",
        '{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
    )
    client = ScriptedClient([failing, passing])
    output = tmp_path / "report.json"
    recovery_case = case(recovery=True, max_attempts=2)

    report = await run_evaluation(
        client=client,
        cases=[recovery_case],
        models=["provider/model"],
        runs=1,
        output=output,
    )

    assert client.calls == 2
    assert [attempt.outcome for attempt in report.results[0].attempts] == [
        "illegal_id",
        "pass",
    ]
    assert report.metrics["provider/model"].recovery_rate == 1
    written = json.loads(output.read_text())
    assert written["results"][0]["final_outcome"] == "pass"
    EvaluationReport.model_validate(written)


@pytest.mark.asyncio
async def test_402_writes_partial_secret_free_report_and_safe_terminal(tmp_path, capsys):
    secret = "sentinel-super-secret"
    client = ScriptedClient([LLMError(f"request failed ({secret})", status_code=402)])
    output = tmp_path / "partial.json"

    report = await run_evaluation(
        client=client,
        cases=[case()],
        models=["provider/model"],
        runs=3,
        output=output,
    )

    rendered = output.read_text()
    assert report.partial is True
    assert report.results[0].attempts[0].outcome == "transport_error"
    assert report.results[0].attempts[0].transport_status == 402
    assert secret not in rendered
    assert secret not in capsys.readouterr().out
    assert report.metrics["provider/model"].semantic_rate == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429])
async def test_non_retryable_transport_status_stops_only_that_model(status, tmp_path):
    report = await run_evaluation(
        client=ScriptedClient(
            [
                LLMError("safe failure", status_code=status),
                call(
                    "get_quotes",
                    '{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
                ),
            ]
        ),
        cases=[case()],
        models=["provider/blocked", "provider/available"],
        runs=1,
        output=tmp_path / "partial.json",
    )

    assert report.partial is True
    assert len(report.results) == 2
    assert report.results[1].model == "provider/available"
    assert report.results[1].final_outcome == "pass"
    assert set(report.run_metrics) == {"provider/blocked", "provider/available"}
    assert set(report.run_metrics["provider/available"]) == {"1"}


@pytest.mark.asyncio
async def test_metrics_are_reported_for_each_numbered_run(tmp_path):
    passing = call(
        "get_quotes",
        '{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
    )
    report = await run_evaluation(
        client=ScriptedClient([passing, passing]),
        cases=[case()],
        models=["provider/model"],
        runs=2,
        output=tmp_path / "report.json",
    )

    assert set(report.run_metrics["provider/model"]) == {"1", "2"}
    assert report.run_metrics["provider/model"]["1"].case_runs == 1
    assert report.run_metrics["provider/model"]["2"].passes == 1


@pytest.mark.asyncio
async def test_usage_costs_include_observed_and_snapshot_estimates(tmp_path):
    response = call(
        "get_quotes",
        '{"pickup_place_id":"pickup","dropoff_place_id":"dropoff"}',
    )
    response.usage = LLMUsage(
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        total_tokens=2_000_000,
        cost=2.5,
    )

    report = await run_evaluation(
        client=ScriptedClient([response]),
        cases=[case()],
        models=["z-ai/glm-4.5-air"],
        runs=1,
        output=tmp_path / "report.json",
    )

    metrics = report.metrics["z-ai/glm-4.5-air"]
    assert metrics.observed_cost == 2.5
    assert metrics.estimated_input_cost == pytest.approx(0.13)
    assert metrics.estimated_output_cost == pytest.approx(0.85)
    assert metrics.estimated_cost == pytest.approx(0.98)
    assert metrics.cost_per_pass == 2.5
    assert report.metrics["overall"].passes == 1
    assert metrics.outcomes["pass"].count == 1


@pytest.mark.asyncio
async def test_missing_key_fails_before_client_construction(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "evals.tool_call_reliability.Settings.from_env",
        lambda: SimpleNamespace(openrouter_api_key=""),
    )

    def fail_if_constructed(config):
        raise AssertionError("client constructed without credentials")

    monkeypatch.setattr(
        "evals.tool_call_reliability.OpenRouterClient",
        fail_if_constructed,
    )
    args = SimpleNamespace(
        model=["primary"],
        runs=1,
        output=tmp_path / "report.json",
        golden_set=FIXTURE,
    )

    assert await _main(args) == 2
