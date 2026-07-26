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
        "book_ride": {
            "type": "object",
            "properties": {"fare_id": {"type": "string"}},
            "required": ["fare_id"],
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
        "cancel_ride": {
            "type": "object",
            "properties": {"trip_id": {"type": "string"}},
            "required": ["trip_id"],
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
        "category": "write_booking",
        "user_message": "Book the first option",
        "preceding_messages": [],
        "tools": [
            "search_places",
            "get_quotes",
            "book_ride",
            "get_trip_status",
            "list_session_trips",
            "cancel_ride",
        ],
        "expected": "tool",
        "expected_tool": "book_ride",
        "allowed_tools": ["book_ride"],
        "expected_arguments": {"fare_id": "fare_1"},
        "allowed_values": {"fare_id": ["fare_1", "fare_2"]},
        "forbidden_tools": ["cancel_ride"],
        "ambiguity": False,
        "write_proposal": True,
        "rationale": "The quoted fare ID must be reused exactly.",
        "recovery": False,
    }
    values.update(changes)
    return GoldenCase.model_validate(values)


def test_golden_set_covers_required_scenarios_and_write_proposals():
    cases = load_cases(FIXTURE)

    assert len(cases) >= 24
    assert sum(item.write_proposal for item in cases) >= 8
    assert {item.expected_tool for item in cases if item.write_proposal} == {
        "book_ride",
        "cancel_ride",
    }
    assert all(item.max_attempts <= 6 for item in cases)
    assert {
        "search-postal-code",
        "search-dropoff-after-pickup",
        "book-ambiguous-it",
        "book-expired-quote",
        "no-session-trips",
        "cancel-named-product",
        "cancel-completed-trip",
        "recover-malformed-json",
        "recover-unknown-tool",
        "recover-invalid-arguments",
    } <= {item.id for item in cases}


@pytest.mark.parametrize(
    ("response", "changes", "outcome"),
    [
        (call("book_ride", "{"), {}, "invalid_json"),
        (call("invented", "{}"), {}, "unknown_tool"),
        (call("book_ride", '{"fare_id":1}'), {}, "schema_mismatch"),
        (call("book_ride", '{"fare_id":"made_up"}'), {}, "illegal_id"),
        (call("cancel_ride", '{"trip_id":"trip_1"}'), {}, "wrong_tool"),
        (call("book_ride", '{"fare_id":"fare_2"}'), {}, "wrong_target"),
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
        (call("book_ride", '{"fare_id":"fare_1"}'), {}, "pass"),
    ],
)
def test_classification_precedence(response, changes, outcome):
    assert classify(case(**changes), response) == outcome


def test_any_bad_parallel_call_fails_with_primary_precedence():
    response = LLMResponse(
        text=None,
        tool_calls=[
            ToolCall(id="one", name="cancel_ride", arguments='{"trip_id":"trip_1"}'),
            ToolCall(id="two", name="book_ride", arguments="{"),
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
    response = call("cancel_ride", '{"trip_id":"trip_1"}')

    assert classify(case(tools=["book_ride"]), response) == "unknown_tool"


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
    from app.agent import tools as production_tools

    async def fail_if_dispatched(*args, **kwargs):
        raise AssertionError("tool handler was dispatched")

    monkeypatch.setitem(production_tools.HANDLERS, "book_ride", fail_if_dispatched)
    client = ScriptedClient([call("book_ride", '{"fare_id":"fare_1"}')])

    await run_evaluation(
        client=client,
        cases=[
            case(
                tools=["book_ride", "cancel_ride"],
                allowed_values={
                    "fare_id": ["fare_1", "fare_2"],
                    "trip_id": ["trip_1"],
                },
            )
        ],
        models=["provider/model"],
        runs=1,
        output=tmp_path / "report.json",
    )

    assert client.tools == [
        [
            {
                "type": "function",
                "function": {
                    "name": "book_ride",
                    "description": (
                        "Propose booking a quoted ride. Requires the user to confirm "
                        "in the UI before anything is booked."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fare_id": {
                                "type": "string",
                                "enum": ["fare_1", "fare_2"],
                            }
                        },
                        "required": ["fare_id"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_ride",
                    "description": (
                        "Propose cancelling a trip. Requires the user to confirm "
                        "in the UI before anything is cancelled."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "trip_id": {
                                "type": "string",
                                "enum": ["trip_1"],
                            }
                        },
                        "required": ["trip_id"],
                        "additionalProperties": False,
                    },
                },
            },
        ]
    ]


@pytest.mark.asyncio
async def test_recovery_is_bounded_and_never_dispatches(monkeypatch, tmp_path):
    from app.agent import tools as production_tools

    async def fail_if_dispatched(*args, **kwargs):
        raise AssertionError("write handler was dispatched")

    monkeypatch.setitem(production_tools.HANDLERS, "book_ride", fail_if_dispatched)
    failing = call("book_ride", '{"fare_id":"invented"}')
    passing = call("book_ride", '{"fare_id":"fare_1"}')
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
                call("book_ride", '{"fare_id":"fare_1"}'),
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
    passing = call("book_ride", '{"fare_id":"fare_1"}')
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
    response = call("book_ride", '{"fare_id":"fare_1"}')
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
