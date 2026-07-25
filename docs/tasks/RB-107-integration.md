# RB-107: Integration - end-to-end tests, security verification, README

| Field | Value |
|---|---|
| Type | Task |
| Wave | 4 (LAST - starts only when RB-101..RB-106 are all closed) |
| Depends on | RB-101, RB-102, RB-103, RB-104, RB-105, RB-106 |
| Blocks | nothing (release gate) |
| Size | M |

## Context

Waves 2 and 3 were built by different agents against frozen contracts (`docs/CONTRACTS.md`), with
cross-component behavior deliberately NOT tested live (RB-104 tested against respx fixtures, not
the running mock; RB-105/106 tested against fakes of each other). This ticket is where everything
meets reality: the full compose stack, real HTTP between containers, the deterministic FakeLLM
driving real tools against the real mock provider, and the audit trail checked end to end. You are
also the integration debugger: when components disagree, the CONTRACT decides who is wrong - fix
the deviating side, log the fix in your close-out, and never change `docs/CONTRACTS.md` itself
without owner approval.

You own `scripts/**`, `api/tests/e2e/**`, and `README.md` (CONTRACTS section 13). For integration
FIXES you may touch other tickets' files - each such fix must be listed in your close-out with
file, cause, and which side deviated from the contract.

## Required reading

1. `docs/CONTRACTS.md` - all of it (you are its enforcement pass)
2. `docs/design.md` sections 8 (invariants - your e2e proves them), 9 (security checklist),
   11 (known limitations - do not "fix" these), 13 (delivery plan context)
3. Every ticket's close-out notes (RB-101..RB-106, bottom of each file) for deviations already
   approved

## Scope

### 1. E2E test suite - `api/tests/e2e/test_full_flow.py`

Runs against the LIVE compose stack with `LLM_MODE=fake` and `MOCK_DETERMINISTIC=1` (set both in
the environment when bringing the stack up; document the exact incantation). Tests connect from
the host to `ws://localhost:8000/ws` (the `websockets` pip package or `httpx-ws` - add to
`api/requirements.txt` as a pinned dev dependency; note it in close-out). Every test uses a fresh
browser-style session_id (uuid4).

Flows (driven purely through the WS + REST surface, exactly like the browser; FakeLLM's scripted
behavior is specified in RB-105 section 2):

- `test_search_quote_book_track_complete` - send
  `"take me from Changi Airport to Marina Bay Sands"`; expect (in order, with a 30s overall
  timeout): `quotes` message (3 items, SGD displays); send `"book uberx"`; expect
  `confirmation_request` (action book, product UberX); POST `/confirm` with the token +
  `"confirm"`; expect `confirmation_resolved` result executed with a trip_id, then `trip_update`
  messages walking `processing -> accepted -> arriving -> in_progress -> completed` (driver
  non-null from accepted onward)
- `test_dismiss_books_nothing` - same up to `confirmation_request`, POST decision `"dismiss"`;
  expect `confirmation_resolved` dismissed; then assert via raw DynamoDB read (boto3 against
  localstack from inside the api container, or expose a helper script) that NO trip row exists
  for this session
- `test_cancel_flow` - book and confirm; after `trip_update` accepted arrives, send
  `"cancel my ride"`; expect `confirmation_request` (action cancel); confirm; expect
  `confirmation_resolved` executed and a `trip_update` with `rider_canceled`
- `test_no_drivers_scenario` - POST `mock-uber /_sim/scenario {"scenario":"no_drivers"}` (from
  inside the compose network via `docker compose exec`); book; expect `trip_update` ending
  `no_drivers_available`, no driver
- `test_confirmation_token_single_use_e2e` - confirm the same token twice over HTTP; second
  returns `expired`; exactly one trip exists
- `test_action_log_completeness` - after `test_search_quote_book_track_complete`'s session:
  read the `action_log` rows for that session and assert presence of the full phase chain per
  CONTRACTS section 12: `requested`(search_places) ... `requested`(book_ride) ->
  `verified`(token_created) -> `verified`(claimed) -> `executed` -> `outcome`(booked), plus
  webhook `outcome` rows with `applied: true` for each lifecycle transition
- `test_grounding_no_pii_in_session` - after a booked flow, dump the session row and every WS
  message received: assert `RIDER_PHONE`'s value appears in NONE of them (it may exist only in
  the action_log `executed` payload and the provider call)

### 2. Demo script - `scripts/demo.sh`

One command for a human demo: checks `.env` exists (else prints the `cp .env.example .env` hint
and which vars to fill), `docker compose up -d --build`, waits for api healthz (30 x 2s cap, then
fails loudly with `docker compose logs --tail 50`), prints the URL `http://localhost:8000` and
three suggested chat lines. `scripts/e2e.sh`: brings the stack up with `LLM_MODE=fake` +
`MOCK_DETERMINISTIC=1` and runs the e2e suite, exiting non-zero on failure (this is the CI
entrypoint later).

### 3. Security verification (design.md section 9, MVP rows) - automate what is cheap, check the rest

Add `api/tests/e2e/test_security.py`:
- `test_no_secret_in_images` - `docker compose config` output contains no value of any secret
  env var (read values from `.env`, assert absence; skip empty ones)
- `test_containers_non_root` - `docker compose exec api id -u` != 0; same for mock-uber
- `test_only_api_published` - parse `docker compose ps --format json`: only api has a host port
  mapping
- `test_webhook_rejects_bad_secret_e2e` - POST to `localhost:8000/webhooks/uber` with a wrong
  secret -> 401
- `test_healthz_headers` - response carries `X-Content-Type-Options: nosniff`
Manual checklist (tick in close-out): `.env` not in either image (`docker compose exec api ls -la /app`),
redaction filter live-check (trigger a log with a phone number via a chat message containing one,
read `docker compose logs api`), `.dockerignore` present in both build contexts, CORS posture
confirmed (no CORS middleware registered anywhere = same-origin only, which is the design.md
section 9 requirement; if any ticket added permissive CORS, remove it).

### 4. `README.md` (repo root)

Sections, tight: What this is (2 lines + the architecture diagram from design.md section 5) ·
Prerequisites (Docker, a filled `.env` - table of every var from CONTRACTS section 2 with
one-line "where to get it") · Run it (`scripts/demo.sh`, plus raw `docker compose up -d --build`) ·
Try it (3 example conversations) · Run the tests (per-suite commands collected from ticket
close-outs + `scripts/e2e.sh`) · Architecture (link to `docs/design.md`, one paragraph, the three
invariants) · Known MVP limitations (copy design.md section 11 verbatim) · Project docs map
(`docs/` inventory).

### 5. Close the loop

Update `docs/rfc.md` Current State (status: MVP implemented; next step: owner demo + prod
hardening backlog) and append a Log entry summarizing integration findings. Update `AGENTS.md`
"Status: EMPTY SCAFFOLD" section and the `Commands` block to reflect reality (real commands only).

## Out of scope

New features, prod Terraform modules, real-Uber/real-LLM e2e (a manual smoke with
`LLM_MODE=openrouter` + a real key is a nice-to-have; report the outcome if you run it, never
commit its transcript), performance work.

## Interfaces produced

The verified, documented, demo-able system. `scripts/e2e.sh` as the single release gate.

## Test plan

The scope IS the test plan (sections 1 and 3). Meta-requirements: e2e suite green twice in a row
from a cold `docker compose down -v` start (proves the idempotent-startup requirement); total
e2e wall time under 5 minutes (deterministic mode keeps simulator delays at zero).

## Security checklist

- [ ] Section 3 automated tests pass; manual items ticked in close-out
- [ ] No secret value or PII in any test fixture, script, or README example

## Acceptance criteria

- [ ] `scripts/e2e.sh` exits 0 from a cold start, twice consecutively
- [ ] `scripts/demo.sh` reaches a working chat UI from a clean machine state (only `.env` filled)
- [ ] All 7 e2e flows + 5 security tests pass
- [ ] README accurate against the real tree (every command in it actually runs)
- [ ] `docs/rfc.md` and `AGENTS.md` updated
- [ ] Integration fixes to other tickets' files each documented (file, cause, deviating side)
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters

## Definition of done

All boxes checked; close-out note at the bottom of this file: integration fixes list, manual
security checklist results, e2e wall time, anything deferred with a reason.
