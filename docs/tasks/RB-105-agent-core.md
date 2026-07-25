# RB-105: Agent core - LLM client, agent loop, tools, confirmation gate, confirm + webhook endpoints

| Field | Value |
|---|---|
| Type | Task |
| Wave | 3 (parallel with RB-106) |
| Depends on | RB-101, RB-103, RB-104 |
| Blocks | RB-107 |
| Size | L (the heart of the system - the three invariants live here) |

## Context

This ticket implements the agent brain and the two invariant-bearing paths (design.md 6.1-6.3, 8):
the LLM-driven tool loop, the confirmation gate that makes it structurally impossible for the
model to execute a booking/cancellation, and the webhook receiver that applies provider status
events. Read design.md section 6.2's sequence diagram before coding - the gate is the single most
important piece of the whole system.

You own `api/app/agent/**`, `api/app/deps.py`, the bodies of `api/app/routers/confirm.py` and
`api/app/routers/webhooks.py` (stubs exist from RB-101 - fill them, keep the `router` name), and
`api/tests/agent/**` (CONTRACTS section 13). Never touch `app/main.py`.

## Required reading

1. `docs/CONTRACTS.md` - sections 4, 5, 6 (tool schemas VERBATIM), 7 (your two endpoints), 8 (WS
   messages you publish), 10 (webhook payload you receive), 12 (action-log phase discipline - your
   code writes almost every row of that table)
2. `docs/design.md` sections 6.1, 6.2, 6.3, 8, 9 (PII rule: guest identity NEVER enters model
   context)
3. Interfaces you consume (already implemented): `app.storage.*` (RB-103 signatures in CONTRACTS
   section 5), `app.providers.uber.UberAdapter` / `ProviderError`, `app.geocode.onemap.OneMapGeocoder`
   / `stub.StubGeocoder` / `GeocodeError` (RB-104), `app.ws.publisher.WsPublisher` protocol (RB-101;
   the real implementation arrives in RB-106 - code against the protocol, tests use a fake)

## Scope

### 1. `app/agent/llm.py` - OpenRouter client

```python
class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str          # raw JSON string as returned by the API

class LLMResponse(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]

class LLMClient(Protocol):
    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse: ...
```

`OpenRouterClient(LLMClient)`: POST `{OPENROUTER_BASE_URL}/chat/completions`, header
`Authorization: Bearer {OPENROUTER_API_KEY}`, body:
`{"model": OPENROUTER_MODEL_PRIMARY, "models": [PRIMARY, FALLBACK], "messages": ...,
"tools": ..., "tool_choice": "auto", "temperature": 0.2, "max_tokens": 1024,
"provider": {"require_parameters": true, "data_collection": "deny"}}`.
Also enable OpenRouter's Response Healing for malformed-JSON repair - CHECK the current request
field at https://openrouter.ai/docs/guides/features/plugins/response-healing at implementation
time (it is an opt-in plugin; do not guess the field name - if unclear, note it in the close-out
and proceed without it, the loop's own malformed-call handling below covers the gap). Timeout 60s.
Non-2xx or timeout -> raise `LLMError(detail)` (never retry here; the loop surfaces a friendly
error). The API key must never be logged.

### 2. `app/agent/fake_llm.py` - deterministic scripted client (`LLM_MODE=fake`)

`FakeLLM(LLMClient)` - keyword-driven script so e2e (RB-107) and demos run with zero network and
zero nondeterminism. Behavior on the LAST user message (case-insensitive):
- contains `" from "` and `" to "` -> emit tool_calls in sequence across successive `complete`
  calls: `search_places(pickup text)`, then `search_places(dropoff text)`, then
  `get_quotes(first place_id of each search result - read them from the tool result messages)`,
  then final text `"Here are your options. Reply 'book <product>' to book."`
- starts with `"book"` -> `book_ride(fare_id of the cheapest quote found in the most recent
  get_quotes tool result in the message history)`, then text `"Please confirm in the card above."`
- contains `"cancel"` -> `list_session_trips()`, then `cancel_ride(trip_id of the most recent
  trip whose status is in CANCELLABLE_STATUSES)`, then text `"Please confirm the cancellation."`
- contains `"status"` -> `list_session_trips()`, then text summarizing statuses from the tool
  result verbatim
- anything else -> text `"I can search, book, track and cancel rides. Try: take me from Changi
  Airport to Marina Bay Sands."`
FakeLLM reads prior tool results from the `messages` list it receives (role="tool" entries) - it
holds no internal state between calls beyond parsing the transcript.

### 3. `app/agent/prompts.py` - system prompt (freeze this text; tweak only with owner approval)

```
You are Route Buddy, a Singapore ride-booking assistant.

Hard rules:
- Answer ONLY from tool results and this conversation. Never invent prices, ETAs, addresses,
  trip statuses, driver details, or IDs. If you do not have the data, say so and offer to look
  it up with a tool.
- Every price, ETA and status you mention must come verbatim from a tool result in this
  conversation.
- To quote rides you MUST first resolve both endpoints with search_places and use the returned
  place_ids. If a place search returns multiple plausible results, ask the user which one they
  mean before quoting.
- book_ride and cancel_ride only PROPOSE an action; the user decides in the confirmation card.
  Never claim a ride is booked or cancelled unless a tool result or a later system message in
  this conversation says so.
- Currency is SGD. Keep replies short. If the user asks for anything outside ride booking,
  say you only handle rides.
```

### 4. `app/agent/tools.py` - tool registry + handlers

Export `TOOL_SCHEMAS` = CONTRACTS section 6 JSON, verbatim. Implement one async handler per tool.
Every handler receives `(session: Session, args: dict, ctx: ToolContext)` where `ToolContext`
bundles repos, provider, geocoder, publisher, correlation_id. Handlers return a JSON-serializable
dict that becomes the tool result message. Validation failures return `{"error": "<reason>"}` and
log `verified`/rejected - they never raise.

- `search_places`: geocoder.search(query); assign `place_id`s (CONTRACTS section 3 convention),
  cache into `session.places`, return `{"places": [{place_id, name, address, postal}]}` -
  NO coordinates in the tool result (the model has no use for them; ids are the handle).
- `get_quotes`: both place_ids must exist in `session.places` else `{"error": "unknown place_id
  <id>; call search_places first"}`. Call `provider.get_quotes(...)` with the places' locations
  and names. Replace `session.quotes` wholesale with the new quotes keyed by fare_id. Publish WS
  `quotes` message (CONTRACTS section 8). Return `{"quotes": [{fare_id, product_name,
  price_display, pickup_eta_minutes, duration_minutes}]}` (display fields only - keeps the model
  grounded in the exact strings it may repeat).
- `book_ride` (GATED): `fare_id` must be in `session.quotes` and `quote.expires_at > now` else
  `{"error": ...}` + `verified`/rejected log. Create `PendingAction` (CONTRACTS section 4;
  payload `{"quote": quote.model_dump(mode="json")}`,
  `expires_at = int(quote.expires_at.timestamp())` (epoch seconds - `expires_at` is a datetime),
  token per convention), `pending_repo.put`, log `verified`/system `{"result": "token_created"}`,
  publish WS `confirmation_request` (section 8, `action: "book"`, summary from the quote,
  `trip_id: null`). Return `{"status": "pending_user_confirmation"}` to the model. NOTHING is
  called on the provider here.
- `get_trip_status`: trip must belong to session (`trip_repo.get` + `trip.session_id` check)
  else error. Call `provider.get_trip(trip.provider_request_id)`; if provider status differs from
  stored, reconcile by writing the trip back with the provider's status and driver via
  `trip_repo.put` (a direct poll of the provider is authoritative ground truth - do NOT route
  this through `apply_status_event`, whose legality check would wrongly reject multi-step jumps
  caused by missed webhooks). Return `{"trip_id", "status", "product_name", "price_display",
  "driver_name": name or null}`.
- `list_session_trips`: `{"trips": [{trip_id, status, product_name, pickup_label,
  dropoff_label, created_at}]}` from `trip_repo.list_by_session`.
- `cancel_ride` (GATED): trip must belong to session AND `trip.status in CANCELLABLE_STATUSES`
  else error. PendingAction payload `{"trip_id": trip_id}`,
  `expires_at = int(time.time()) + 120` (epoch seconds).
  WS `confirmation_request` with `action: "cancel"`, summary from the trip's quote,
  `trip_id` set. Return `{"status": "pending_user_confirmation"}`.

Action-log discipline for every handler per CONTRACTS section 12: `requested`/llm on entry (tool
name + raw args), then `outcome`/llm (read tools) or `verified` (gated/validation paths).

### 5. `app/agent/loop.py` + `app/agent/service.py`

`AgentServiceImpl(AgentService)` - `handle_user_message(session_id, text)`:
1. Rate limit: in-memory token bucket per session_id, 20 msgs/min; exceeded -> publish WS
   `error` "You're sending messages too quickly, give me a moment." and return.
   `# ponytail: in-memory rate limiter, single instance; move to DynamoDB counters if we ever scale out`
2. Load session (`SessionRepo.get`) or create new (`Session(session_id=..., created_at=now, ...)`).
3. Append `{"role": "user", "content": text}`.
4. Loop, max 6 iterations: build messages = `[{"role": "system", "content": SYSTEM_PROMPT}]`
   + session.messages; call `llm.complete(messages, TOOL_SCHEMAS)`.
   - If `tool_calls`: for each - parse `arguments` with `json.loads`; on JSONDecodeError log
     `verified`/rejected `{"error": "malformed_arguments"}` and use result
     `{"error": "malformed tool arguments, please retry with valid JSON"}`; unknown tool name ->
     same pattern. Otherwise Pydantic-validate args against the schema and dispatch the handler.
     Append the assistant tool_calls message and each tool result
     (`{"role": "tool", "tool_call_id": ..., "content": json.dumps(result)}`) to session.messages.
     Continue loop.
   - If `text`: append assistant message, publish WS `assistant_msg`, break.
   - Iteration 6 with no text: publish `assistant_msg` "Sorry, I got stuck - could you rephrase?"
5. On `LLMError`: publish WS `error` "The assistant is unavailable right now, try again shortly."
6. `SessionRepo.put(session)` in a `finally`. Handler must never raise to the caller (RB-106
   calls this from the WS receive loop).

Each user turn gets ONE `correlation_id` for read tools; each GATED tool call creates its OWN
correlation_id stored in the PendingAction (it spans the confirm flow).

### 6. `app/routers/confirm.py` - POST /confirm (fill the RB-101 stub)

Body `{"token": str, "decision": "confirm" | "dismiss"}` (Pydantic). Rate limit 10/min per
session (session_id comes from the claimed action; pre-claim, bucket by client host - simplest
correct: bucket by token string). Flow:
1. `pending_repo.claim(token)` -> None: respond `{"result": "expired", "trip_id": null}` and log
   `verified`/user `{"result": "expired_or_unknown_token"}` with correlation_id `"unknown"`
   (we no longer know the action). Publish nothing (no session known).
2. Claimed + `decision == "dismiss"`: log `outcome`/user `{"result": "aborted_by_user"}`
   (correlation_id from the action); publish WS `confirmation_resolved`
   `{result: "dismissed"}`; respond `{"result": "dismissed", "trip_id": null}` (every /confirm
   response carries both keys per CONTRACTS section 7 - `failed` below responds
   `{"result": "failed", "trip_id": null}` likewise).
3. Claimed + `decision == "confirm"`:
   - log `verified`/user `{"result": "claimed"}`
   - `action_type == "book"`: rebuild `Quote` from payload; build `GuestProfile` from Settings
     (`RIDER_FIRST_NAME/LAST_NAME/PHONE`) - THIS is the only place guest PII enters a request,
     server-side (design.md 9); log `executed`/system `{"endpoint": "POST /v1/guests/trips",
     "product_id", "fare_id"}`; call `provider.book(quote, guest)`. Success: build `Trip`
     (trip_id `f"uber:{state.provider_request_id}"`, CONTRACTS section 3), `trip_repo.put`,
     log `outcome`/system `{"result": "booked", "trip_id"}`, publish `confirmation_resolved`
     `{result: "executed", trip_id}` AND `trip_update` (status processing), append a
     `{"role": "system", "content": "Booking executed: trip <trip_id> status processing"}`
     message to the session (so the model knows on the next turn). `ProviderError`: log
     `outcome`/system with the error code, publish `confirmation_resolved`
     `{result: "failed"}`, respond `{"result": "failed"}`.
   - `action_type == "cancel"`: same shape with `provider.cancel(trip.provider_request_id)`;
     on success `apply_status_event(trip_id, f"cancel_{uuid4().hex[:8]}", rider_canceled, None)`,
     publish `confirmation_resolved` + `trip_update`.

### 7. `app/routers/webhooks.py` - POST /webhooks/uber (fill the RB-101 stub)

1. Verify `X-Webhook-Secret` with `hmac.compare_digest` against Settings value; mismatch/absent
   -> 401. Missing configured secret (empty env) -> 503 (refuse to run open).
2. Parse payload (CONTRACTS section 10; Pydantic). `trip_id = f"uber:{meta.resource_id}"`.
3. `trip_repo.apply_status_event(trip_id, event_id, TripStatus(meta.status), driver=None)`.
   - Applied: if the new status is `accepted` or `driver_redispatched`, call
     `provider.get_trip(meta.resource_id)` once to fetch driver details and store them by
     writing the updated trip back with `trip_repo.put(trip_with_driver)` - never by calling
     `apply_status_event` again (same-status transitions are illegal there and return None).
     Log `outcome`/webhook `{"event_id", "status", "applied": true}`. Publish WS `trip_update`
     to `trip.session_id`.
   - Not applied (duplicate/illegal/unknown trip): log `outcome`/webhook `{"applied": false,
     "reason": "duplicate_or_unknown"}`.
4. Always `204` when authenticated (even unknown trip - no enumeration oracle).

### 8. `app/deps.py` - composition root

Module-level singletons built from `Settings`: repos (RB-103), provider (`UberAdapter`), geocoder
(`OneMapGeocoder`, or `StubGeocoder(DEMO_PLACES)` when `LLM_MODE == "fake"` so fake mode needs no
OneMap credentials), llm (`OpenRouterClient` or `FakeLLM` by `LLM_MODE`). For publishing, always
call `app.registry.get_publisher()` AT USE TIME (never cache the publisher at import - RB-106
registers the real `ConnectionManager` during startup, after imports). At the END of this module,
call `app.registry.set_agent_service(<the built AgentServiceImpl>)` - `main.py` (RB-101) imports
`app.deps` at startup precisely to trigger this registration. You own no `set_publisher`; that is
RB-106's side of the `app.registry` seam.

## Out of scope

WebSocket transport and UI (RB-106 - you publish through the `WsPublisher` protocol only),
storage internals, provider/geocoder internals, e2e (RB-107).

## Interfaces produced

- The real `AgentService`, registered into `app.registry` when `app.deps` is imported (RB-106
  fetches it per message via `app.registry.get_agent_service()`; neither ticket imports the other)
- Working `/confirm` and `/webhooks/uber` endpoints
- `FakeLLM` behavior contract above (RB-107's e2e is scripted against it)

## Test plan (pytest; `CapturePublisher` fake recording published messages, installed via
`app.registry.set_publisher`; `StubGeocoder`;
real repos against LocalStack - run in-container like RB-103; FakeLLM or hand-built `ScriptedLLM`
returning queued `LLMResponse`s for exact control)

`tests/agent/test_loop.py`:
- `test_read_tool_roundtrip` - script: search_places call, then text; assert tool result fed
  back, assistant_msg published, session persisted with 4 messages (user, assistant+tool_call,
  tool, assistant)
- `test_malformed_arguments_refused` - tool call with `arguments='{"query":'` -> error result
  fed to model, `verified` log entry with `malformed_arguments`, loop continues
- `test_unknown_tool_refused`
- `test_iteration_cap` - script 7 tool calls -> after 6, apology text published
- `test_rate_limit` - 21 rapid messages -> 21st publishes WS error, LLM called 20 times
- `test_llm_error_publishes_friendly_error`

`tests/agent/test_tools.py`:
- `test_get_quotes_unknown_place_refused` - error result + `verified`/rejected logged + provider
  NOT called
- `test_get_quotes_happy` - session.quotes replaced, WS `quotes` published, result contains only
  display fields (assert NO lat/lng keys anywhere in the tool result)
- `test_book_ride_expired_quote_refused`
- `test_book_ride_creates_pending_action_and_card` - pending_actions row exists with frozen
  quote payload; WS `confirmation_request` published; provider.book NOT called (assert via spy)
- `test_cancel_ride_not_cancellable_refused` - trip in `completed` -> error
- `test_trip_ownership_enforced` - get_trip_status with another session's trip_id -> error

`tests/agent/test_confirm.py` (TestClient):
- `test_confirm_executes_book` - seed pending action; POST confirm -> provider.book called with
  the FROZEN quote (spy asserts fare_id) and guest from env; trip stored; log has
  verified+executed+outcome; WS `confirmation_resolved` executed + `trip_update` published
- `test_confirm_is_single_use` - second POST with same token -> `{"result": "expired"}`,
  provider called exactly once
- `test_double_submit_race` - `asyncio.gather` two confirms -> exactly one provider.book call
- `test_dismiss` - provider never called, `outcome` log `aborted_by_user`
- `test_expired_token` - pending action with `expires_at` in the past -> expired, provider not
  called
- `test_provider_failure_reports_failed` - provider raises `ProviderError(fare_expired)` ->
  result failed, `outcome` log carries the code
- `test_llm_cannot_execute` - grep-level structural test: `book_ride` handler source contains no
  reference to `provider.book` (import the handler module, assert
  `"provider.book" not in inspect.getsource(tools_module.handle_book_ride)`), and the only
  callsite of `provider.book(` under `app/` is `routers/confirm.py` (walk the files and assert)

`tests/agent/test_webhooks.py` (TestClient):
- `test_bad_secret_401`, `test_missing_secret_config_503`
- `test_happy_event_applies_and_publishes` - seed trip processing; event accepted -> trip
  updated, `trip_update` published to the right session, outcome logged applied=true
- `test_duplicate_event_ignored` - same event_id twice -> one update, second logged applied=false
- `test_unknown_trip_204_no_publish`
- `test_illegal_transition_ignored` - completed -> accepted event refused

`tests/agent/test_fake_llm.py`:
- the four scripted flows produce the specified tool-call sequences against canned transcripts

## Security checklist

- [ ] Guest PII (RIDER_*) appears ONLY in `routers/confirm.py` provider call - never in any
      message appended to `session.messages`, never in tool results, never in WS payloads,
      never in logs (test: after a full book flow, assert RIDER_PHONE value absent from session
      messages and captured WS messages)
- [ ] `OPENROUTER_API_KEY` / webhook secret never logged
- [ ] `hmac.compare_digest` for the webhook secret
- [ ] `data_collection: "deny"` present in every OpenRouter request body

## Acceptance criteria

- [ ] All tests above pass (documented in-container command, like RB-103)
- [ ] The structural `test_llm_cannot_execute` proves the gate: no execution path from a model
      tool call to `provider.book`/`provider.cancel`
- [ ] Action-log rows match CONTRACTS section 12 for every flow (spot-assert in tests via raw
      DynamoDB reads)
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters
- [ ] Only owned files created/modified (incl. filling exactly the two router stubs)

## Definition of done

All boxes checked; close-out note at the bottom of this file: what was built, Response Healing
field outcome, deviations (owner approval first), exact verify commands.
