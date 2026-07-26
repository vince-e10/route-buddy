"""Secret-free live evaluation for Route Buddy's production OpenRouter path."""

import argparse
import asyncio
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.llm import LLMClient, LLMError, LLMResponse, OpenRouterClient, ToolCall
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tool_contracts import ARG_MODELS, TOOL_SCHEMAS
from app.config import Settings


Outcome = Literal[
    "pass",
    "invalid_json",
    "unknown_tool",
    "schema_mismatch",
    "illegal_id",
    "wrong_tool",
    "wrong_target",
    "should_clarify",
    "unnecessary_refusal",
    "no_response",
    "transport_error",
]
OUTCOMES = [
    "pass",
    "invalid_json",
    "unknown_tool",
    "schema_mismatch",
    "illegal_id",
    "wrong_tool",
    "wrong_target",
    "should_clarify",
    "unnecessary_refusal",
    "no_response",
    "transport_error",
]

PRICE_SNAPSHOT = {
    "accessed": "2026-07-26",
    "currency": "USD",
    "unit": "per_million_tokens",
    "models": {
        "z-ai/glm-4.5-air": {
            "input": 0.13,
            "output": 0.85,
            "source": "https://openrouter.ai/z-ai/glm-4.5-air",
        },
        "minimax/minimax-m2": {
            "input": 0.255,
            "output": 1.02,
            "source": "https://openrouter.ai/minimax/minimax-m2",
        },
        "nvidia/nemotron-3-ultra-550b-a55b:free": {
            "input": 0.0,
            "output": 0.0,
            "source": "https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b:free",
        },
        "google/gemma-4-31b-it:free": {
            "input": 0.0,
            "output": 0.0,
            "source": "https://openrouter.ai/google/gemma-4-31b-it:free",
        },
    },
}

STRUCTURAL_FAILURES = {
    "invalid_json",
    "unknown_tool",
    "schema_mismatch",
    "no_response",
    "transport_error",
}


class GoldenCase(BaseModel):
    id: str
    category: str
    user_message: str
    preceding_messages: list[dict]
    tools: list[str]
    expected: Literal["tool", "clarify", "text"]
    expected_tool: str | None
    allowed_tools: list[str]
    expected_arguments: dict
    allowed_values: dict[str, list]
    forbidden_tools: list[str]
    ambiguity: bool
    write_proposal: bool
    rationale: str
    required_text_any: list[str] = Field(default_factory=list)
    forbidden_text: list[str] = Field(default_factory=list)
    recovery: bool
    max_attempts: int = Field(default=1, ge=1, le=6)


class AttemptResult(BaseModel):
    attempt: int
    outcome: Outcome
    latency_ms: float
    model: str | None = None
    provider: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    observed_cost: float | None = None
    transport_status: int | None = None
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class CaseResult(BaseModel):
    case_id: str
    model: str
    run: int
    write_proposal: bool
    recovery: bool
    final_outcome: Outcome
    attempts: list[AttemptResult]


class OutcomeMetric(BaseModel):
    count: int
    rate: float


class Metrics(BaseModel):
    case_runs: int
    responses: int
    passes: int
    outcomes: dict[str, OutcomeMetric]
    wrong_write_target_count: int
    structural_rate: float
    semantic_rate: float
    write_proposal_rate: float | None
    recovery_rate: float | None
    recovery_retry_count: int
    latency_mean_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    wall_time_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    observed_cost: float
    estimated_input_cost: float | None
    estimated_output_cost: float | None
    estimated_cost: float | None
    cost_per_pass: float | None


class EvaluationReport(BaseModel):
    generated_at: str
    fixture_sha256: str
    requested_models: list[str]
    requested_runs: int
    partial: bool
    partial_reason: str | None = None
    wall_time_ms: float
    price_snapshot: dict
    results: list[CaseResult]
    metrics: dict[str, Metrics]
    run_metrics: dict[str, dict[str, Metrics]]


def load_cases(path: Path) -> list[GoldenCase]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, list):
        raise ValueError("golden set must be a JSON array")
    cases = [GoldenCase.model_validate(item) for item in payload]
    if len(cases) < 24 or len({item.id for item in cases}) != len(cases):
        raise ValueError("golden set must contain at least 24 uniquely named cases")
    if sum(item.write_proposal for item in cases) < 8:
        raise ValueError("golden set must contain at least 8 write proposals")
    if {
        item.expected_tool for item in cases if item.write_proposal
    } != {"book_ride", "cancel_ride"}:
        raise ValueError("write proposals must cover book_ride and cancel_ride")
    available = set(ARG_MODELS)
    if any(
        not set(item.tools) <= available
        or not set(item.allowed_tools) <= set(item.tools)
        or not set(item.forbidden_tools) <= set(item.tools)
        for item in cases
    ):
        raise ValueError("golden set contains an invalid tool contract")
    if any(
        item.expected != "tool" and not item.required_text_any
        for item in cases
    ):
        raise ValueError("text and clarification cases require expected text evidence")
    return cases


def classify(case: GoldenCase, response: LLMResponse) -> Outcome:
    if not response.tool_calls:
        if not response.text:
            return "no_response"
        if case.expected == "tool":
            return "unnecessary_refusal"
        lowered = response.text.lower()
        matches = any(value.lower() in lowered for value in case.required_text_any)
        forbidden = any(value.lower() in lowered for value in case.forbidden_text)
        if matches and not forbidden:
            return "pass"
        return "should_clarify" if case.expected == "clarify" else "unnecessary_refusal"

    failures: list[Outcome] = []
    parsed_calls: list[tuple[ToolCall, dict]] = []
    for call in response.tool_calls:
        try:
            arguments = json.loads(call.arguments)
        except (json.JSONDecodeError, TypeError):
            failures.append("invalid_json")
            continue
        if call.name not in ARG_MODELS or call.name not in case.tools:
            failures.append("unknown_tool")
            continue
        try:
            arguments = ARG_MODELS[call.name].model_validate(arguments).model_dump()
        except ValidationError:
            failures.append("schema_mismatch")
            continue
        parsed_calls.append((call, arguments))

    if failures:
        for outcome in ("invalid_json", "unknown_tool", "schema_mismatch"):
            if outcome in failures:
                return outcome
    if case.expected != "tool":
        return "should_clarify"
    if any(
        call.name in case.forbidden_tools or call.name not in case.allowed_tools
        for call, _ in parsed_calls
    ):
        return "wrong_tool"
    if len(response.tool_calls) != 1 or any(
        call.name != case.expected_tool for call, _ in parsed_calls
    ):
        return "wrong_tool"

    arguments = parsed_calls[0][1]
    for field, allowed in case.allowed_values.items():
        if field in arguments and arguments[field] not in allowed:
            return "illegal_id"
    if arguments != case.expected_arguments:
        return "wrong_target"
    return "pass"


def nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _assistant_message(response: LLMResponse) -> dict:
    return {
        "role": "assistant",
        "content": response.text,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in response.tool_calls
        ],
    }


async def _evaluate_case(
    client: LLMClient,
    case: GoldenCase,
    model: str,
    run: int,
) -> tuple[CaseResult, int | None]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *case.preceding_messages,
        {"role": "user", "content": case.user_message},
    ]
    schemas = [
        schema for schema in TOOL_SCHEMAS if schema["function"]["name"] in case.tools
    ]
    attempts: list[AttemptResult] = []
    stop_status = None
    limit = case.max_attempts if case.recovery else 1

    for number in range(1, limit + 1):
        started = time.perf_counter()
        try:
            response = await client.complete(messages, schemas, model=model)
            outcome = classify(case, response)
            usage = response.usage
            attempts.append(
                AttemptResult(
                    attempt=number,
                    outcome=outcome,
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    model=response.model,
                    provider=response.provider,
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
                    observed_cost=usage.cost if usage else None,
                    text=response.text,
                    tool_calls=response.tool_calls,
                )
            )
        except LLMError as error:
            attempts.append(
                AttemptResult(
                    attempt=number,
                    outcome="transport_error",
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    transport_status=error.status_code,
                )
            )
            if error.status_code in {401, 402, 403, 404, 429}:
                stop_status = error.status_code
            break
        if outcome == "pass" or not response.tool_calls:
            break
        messages.append(_assistant_message(response))
        for call in response.tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        {
                            "error": (
                                "evaluation rejected this proposal; retry with the "
                                "available tools and known IDs"
                            )
                        }
                    ),
                }
            )

    return (
        CaseResult(
            case_id=case.id,
            model=model,
            run=run,
            write_proposal=case.write_proposal,
            recovery=case.recovery,
            final_outcome=attempts[-1].outcome,
            attempts=attempts,
        ),
        stop_status,
    )


def _metrics(results: list[CaseResult], model: str | None = None) -> Metrics:
    selected = [
        result for result in results if model is None or result.model == model
    ]
    attempts = [attempt for result in selected for attempt in result.attempts]
    total = len(attempts)
    response_passes = sum(attempt.outcome == "pass" for attempt in attempts)
    case_passes = sum(result.final_outcome == "pass" for result in selected)
    write_results = [result for result in selected if result.write_proposal]
    recovery_results = [result for result in selected if result.recovery]
    observed_cost = sum(attempt.observed_cost or 0 for attempt in attempts)
    prices = PRICE_SNAPSHOT["models"].get(model) if model else None
    estimated_input_cost = None
    estimated_output_cost = None
    if prices is not None:
        estimated_input_cost = (
            sum(attempt.prompt_tokens for attempt in attempts)
            * prices["input"]
            / 1_000_000
        )
        estimated_output_cost = (
            sum(attempt.completion_tokens for attempt in attempts)
            * prices["output"]
            / 1_000_000
        )
    elif model is None:
        estimated_input_cost = sum(
            _metrics(results, name).estimated_input_cost or 0
            for name in {result.model for result in results}
        )
        estimated_output_cost = sum(
            _metrics(results, name).estimated_output_cost or 0
            for name in {result.model for result in results}
        )
    estimated_cost = (
        estimated_input_cost + estimated_output_cost
        if estimated_input_cost is not None and estimated_output_cost is not None
        else None
    )
    latencies = [attempt.latency_ms for attempt in attempts]
    return Metrics(
        case_runs=len(selected),
        responses=total,
        passes=case_passes,
        outcomes={
            outcome: OutcomeMetric(
                count=sum(attempt.outcome == outcome for attempt in attempts),
                rate=(
                    sum(attempt.outcome == outcome for attempt in attempts) / total
                    if total
                    else 0
                ),
            )
            for outcome in OUTCOMES
        },
        wrong_write_target_count=sum(
            attempt.outcome == "wrong_target"
            for result in write_results
            for attempt in result.attempts
        ),
        structural_rate=(
            sum(attempt.outcome not in STRUCTURAL_FAILURES for attempt in attempts) / total
            if total
            else 0
        ),
        semantic_rate=response_passes / total if total else 0,
        write_proposal_rate=(
            sum(result.final_outcome == "pass" for result in write_results)
            / len(write_results)
            if write_results
            else None
        ),
        recovery_rate=(
            sum(result.final_outcome == "pass" for result in recovery_results)
            / len(recovery_results)
            if recovery_results
            else None
        ),
        recovery_retry_count=sum(
            max(0, len(result.attempts) - 1) for result in recovery_results
        ),
        latency_mean_ms=sum(latencies) / total if total else 0,
        latency_p50_ms=nearest_rank(latencies, 0.5),
        latency_p95_ms=nearest_rank(latencies, 0.95),
        wall_time_ms=sum(latencies),
        prompt_tokens=sum(attempt.prompt_tokens for attempt in attempts),
        completion_tokens=sum(attempt.completion_tokens for attempt in attempts),
        total_tokens=sum(attempt.total_tokens for attempt in attempts),
        observed_cost=observed_cost,
        estimated_input_cost=estimated_input_cost,
        estimated_output_cost=estimated_output_cost,
        estimated_cost=estimated_cost,
        cost_per_pass=observed_cost / case_passes if case_passes else None,
    )


def _write_report(report: EvaluationReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2) + "\n")


async def run_evaluation(
    *,
    client: LLMClient,
    cases: list[GoldenCase],
    models: list[str],
    runs: int,
    output: Path,
    fixture_sha256: str = "in-memory",
) -> EvaluationReport:
    started = time.perf_counter()
    results: list[CaseResult] = []
    partial_models: dict[str, int] = {}
    for model in models:
        stop_model = False
        for run in range(1, runs + 1):
            for case in cases:
                result, stop_status = await _evaluate_case(client, case, model, run)
                results.append(result)
                if stop_status is not None:
                    partial_models[model] = stop_status
                    stop_model = True
                    break
            if stop_model:
                break

    metrics = {model: _metrics(results, model) for model in models}
    metrics["overall"] = _metrics(results)
    run_metrics = {
        model: {
            str(run): _metrics(
                [
                    result
                    for result in results
                    if result.model == model and result.run == run
                ],
                model,
            )
            for run in range(1, runs + 1)
            if any(
                result.model == model and result.run == run
                for result in results
            )
        }
        for model in models
    }
    report = EvaluationReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        fixture_sha256=fixture_sha256,
        requested_models=models,
        requested_runs=runs,
        partial=bool(partial_models),
        partial_reason=(
            ", ".join(
                f"{model}:http_{status}"
                for model, status in partial_models.items()
            )
            if partial_models
            else None
        ),
        wall_time_ms=round((time.perf_counter() - started) * 1000, 3),
        price_snapshot=PRICE_SNAPSHOT,
        results=results,
        metrics=metrics,
        run_metrics=run_metrics,
    )
    _write_report(report, output)
    print(
        f"wrote {len(results)} case-runs to {output}; "
        f"partial={'yes' if partial_models else 'no'}"
    )
    for model in [*models, "overall"]:
        item = metrics[model]
        nonpasses = item.case_runs - item.passes
        failures = ",".join(
            f"{outcome}={value.count}"
            for outcome, value in item.outcomes.items()
            if outcome != "pass" and value.count
        ) or "none"
        print(
            f"{model}: pass={item.passes}/{item.case_runs} "
            f"structural={item.structural_rate:.1%} semantic={item.semantic_rate:.1%} "
            f"nonpasses={nonpasses} [{failures}] cost=${item.observed_cost:.6f}"
        )
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        help="Pinned OpenRouter model ID, or primary/fallback",
    )
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=Path(__file__).with_name("golden-set.json"),
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    return args


async def _main(args: argparse.Namespace) -> int:
    config = Settings.from_env()
    if not config.openrouter_api_key:
        print("OpenRouter credentials are not configured in the local environment.")
        return 2
    aliases = {
        "primary": config.openrouter_model_primary,
        "fallback": config.openrouter_model_fallback,
    }
    models = [aliases.get(model, model) for model in args.model]
    raw_fixture = args.golden_set.read_bytes()
    cases = load_cases(args.golden_set)
    client = OpenRouterClient(config)
    try:
        await run_evaluation(
            client=client,
            cases=cases,
            models=models,
            runs=args.runs,
            output=args.output,
            fixture_sha256=hashlib.sha256(raw_fixture).hexdigest(),
        )
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main(_parse_args())))
    except Exception:
        print("Evaluation configuration, fixture, or output is invalid.")
        raise SystemExit(2) from None
