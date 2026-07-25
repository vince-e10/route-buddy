# RB-102: mock-uber - Guest Rides API mock with driver lifecycle simulator

| Field | Value |
|---|---|
| Type | Task |
| Wave | 2 (parallel with RB-103, RB-104) |
| Depends on | RB-101 |
| Blocks | RB-107 |
| Size | L |

## Context

There is no self-serve Uber API in 2026 (design.md 3.1) - so this service IS our Uber. It mirrors
the real Uber Guest Rides API contract (paths, field names, status values, webhook payloads,
verbatim) so that swapping to real Uber later is credentials + base URL. It also owns ALL driver
lifecycle simulation - the api container never simulates anything (design decision: simulation
logic must live behind the provider boundary so it cannot be stranded on swap).

You own `mock-uber/app/**` and `mock-uber/tests/**` only (CONTRACTS section 13). RB-101 already
created the Dockerfile, requirements.txt, and a healthz-only `app/main.py` which you replace
(keep `/healthz` working).

## Required reading

1. `docs/CONTRACTS.md` sections 2 (env), 9 (your endpoint contract - implement VERBATIM),
   10 (lifecycle + webhook contract), 4 (TripStatus, LEGAL_TRANSITIONS, CANCELLABLE_STATUSES -
   copy these two constants + the status enum into `mock-uber/app/models.py`; mock-uber does not
   import from `api/`)
2. `docs/design.md` sections 3.1 (real Uber contract + state machine) and 6.4 (your component)

## Scope

1. **`app/models.py`**: Pydantic request/response models for every endpoint in CONTRACTS section 9,
   plus `TripStatus` / `LEGAL_TRANSITIONS` / `CANCELLABLE_STATUSES` copied verbatim from CONTRACTS
   section 4.
2. **`app/store.py`**: in-memory state (plain dicts + `asyncio.Lock`): issued fares
   (`fare_id -> {product_id, value, expires_at, pickup, dropoff}`), trips
   (`request_id -> trip record`), active scenario. In-memory is deliberate (stateless restarts
   acceptable for a simulator); add `# ponytail: in-memory store, swap for redis if the mock ever needs restarts mid-demo`.
3. **`app/main.py`**: FastAPI app with:
   - Auth middleware on `/v1/*`: require `authorization` header starting `Bearer ` AND an
     `x-uber-organizationuuid` header, else `401 {"code":"unauthorized"}` (values not validated -
     the mock checks plumbing, not identity)
   - `POST /v1/guests/trips/estimates` - 3 products (`uberx-sg` 1.0, `comfort-sg` 1.3,
     `uberxl-sg` 1.6), fare formula `(4.0 + 0.9*km + 0.15*minutes) * product_multiplier * surge`,
     haversine distance, 30 km/h, 2dp rounding, `fare.expires_at = now + 300s`. Response shape
     EXACTLY per CONTRACTS section 9 (field names are load-bearing - the adapter in RB-104 parses
     them from the same spec). Store issued fare_ids.
   - `POST /v1/guests/trips` - validations and error codes exactly per CONTRACTS section 9
     (`invalid_product` 404, `fare_expired` 410, `invalid_guest` 400 with E.164 check
     `^\+\d{7,15}$`). On success store trip in `processing` and start the simulator task.
   - `GET /v1/guests/trips/{request_id}` and `DELETE /v1/guests/trips/{request_id}` per CONTRACTS
     section 9 (DELETE: only from `CANCELLABLE_STATUSES`, else `409 {"code":"not_cancellable"}`;
     cancellation emits a webhook like any other transition).
   - `POST /_sim/scenario` per CONTRACTS section 9 (no auth; applies to NEXT trip for
     `no_drivers`/`driver_cancel`, to subsequent estimates for `surge`; `reset` clears).
   - `GET /healthz` preserved.
4. **`app/sim.py`**: one `asyncio.Task` per trip walking the happy path with delays
   `3s -> 8s -> 10s -> 20s` each divided by `SIM_SPEED` (float env; `MOCK_DETERMINISTIC=1` makes
   all delays zero and fares jitter-free). Driver assigned at `accepted`: cycle through a fixed
   list of 5 names (e.g. "Tan Wei Ming", "Siti Rahayu", "Kumar Ravi", "Lim Hui Fen", "Ahmad
   Faizal"), rating deterministic per name in [4.6, 5.0]. Scenario branches: `no_drivers` ->
   `processing -> no_drivers_available` (after the first delay); `driver_cancel` ->
   `processing -> accepted -> driver_canceled`. Every transition: (a) asserts legality against
   `LEGAL_TRANSITIONS` (raise + log if violated - that is a simulator bug), (b) updates the store,
   (c) fires the webhook.
5. **Webhook emitter** (in `sim.py`): POST CONTRACTS section 10 payload to `WEBHOOK_TARGET_URL`
   with header `X-Webhook-Secret: $WEBHOOK_SHARED_SECRET`; fresh `event_id` per event
   (`evt_<uuid4hex>`); retry up to 3 times (1s/2s/4s backoff) on non-2xx/connection error, then
   drop and log a warning. A rider cancel (DELETE) also emits. Webhook failures never break the
   simulator or the API response.

## Out of scope

Scheduled/Reserve rides, PUT trip update, receipts, driver messaging, tips, real OAuth token
validation, persistence across restarts.

## Interfaces produced

- The HTTP contract of CONTRACTS section 9 at `http://mock-uber:8001` (RB-104's adapter and
  RB-107's e2e consume it)
- Webhooks per CONTRACTS section 10 to the api (RB-105's receiver consumes them)

## Test plan (pytest, httpx ASGI client; set `MOCK_DETERMINISTIC=1` and monkeypatch the webhook
emitter to capture instead of POST unless the test targets retries)

`tests/test_auth.py`:
- estimates without `authorization` header -> 401; without org header -> 401; with both -> 200

`tests/test_estimates.py`:
- returns exactly 3 products with ids `uberx-sg`, `comfort-sg`, `uberxl-sg`
- fare formula spot check: pickup (1.28345, 103.86081) to dropoff (1.35735, 103.98803)
  (Marina Bay Sands -> Changi Airport, ~16.5 km haversine): UberX `fare.value ==
  round(4.0 + 0.9*km + 0.15*(km/30*60), 2)` recomputed in the test from the same formula
- Comfort value == UberX value * 1.3 (2dp); `fare.expires_at` within [now+295, now+305]
- after `POST /_sim/scenario {"scenario":"surge","surge_multiplier":2.0}`, values double

`tests/test_trips.py`:
- create with unknown product -> 404 `invalid_product`; with unissued fare_id -> 410
  `fare_expired`; with phone "12345" -> 400 `invalid_guest`
- happy create -> 200, `status == "processing"`, `request_id` starts `req_`
- deterministic mode: after create, poll GET until `completed`; observed status sequence is
  exactly `processing, accepted, arriving, in_progress, completed`; driver is non-null from
  `accepted` onward
- DELETE while `accepted` -> 200 `rider_canceled`; DELETE after `completed` -> 409

`tests/test_scenarios.py`:
- `no_drivers`: next trip ends `no_drivers_available`, no driver ever assigned
- `driver_cancel`: next trip ends `driver_canceled` after `accepted`
- `reset` clears surge (estimates return to base values)

`tests/test_webhooks.py`:
- captured webhook sequence for a happy trip = one event per transition, each with unique
  `event_id`, correct `meta.resource_id` and `meta.status`, header `X-Webhook-Secret` present
- emitter retries: fake target failing twice then succeeding -> exactly 3 attempts, event
  delivered once

`tests/test_state_machine.py`:
- for every (from, to) NOT in `LEGAL_TRANSITIONS`, the store's transition function refuses

## Security checklist

- [ ] `WEBHOOK_SHARED_SECRET` value never logged (RB-101's redaction is api-side; here just never
      log the header/secret)
- [ ] No guest PII in log lines (log request_ids, not names/phones)

## Acceptance criteria

- [ ] All tests above pass: `cd mock-uber && python -m pytest tests/ -v`
- [ ] `docker compose up -d --build mock-uber` serves the contract in-network; healthz still 200
- [ ] Response bodies byte-compatible with CONTRACTS section 9 field names (spot-check with curl
      from inside the network: `docker compose exec api python -c "import httpx; ..."` or a
      temporary curl container)
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters
- [ ] Only files under `mock-uber/app/**` and `mock-uber/tests/**` were created/modified

## Definition of done

All boxes checked; close-out note at the bottom of this file: what was built, deviations (owner
approval required first), and the exact commands you ran to verify.
