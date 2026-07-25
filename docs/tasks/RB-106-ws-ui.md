# RB-106: WebSocket transport + chat UI

| Field | Value |
|---|---|
| Type | Task |
| Wave | 3 (parallel with RB-105) |
| Depends on | RB-101, RB-103 |
| Blocks | RB-107 |
| Size | M |

## Context

The browser-facing layer (design.md 6.7): a WebSocket endpoint that carries chat + live updates,
a `ConnectionManager` implementing the `WsPublisher` protocol, and a single static chat page. All
substance lives server-side; this layer renders structured cards and forwards user input. RB-105
is built in parallel - the ONLY thing you share with it is `app.registry` (built in RB-101): you
register the publisher there and fetch the `AgentService` from there; in tests you install a fake
service via the same registry. Live pairing with the real agent is proven in RB-107.

You own `api/app/ws/manager.py`, the body of `api/app/routers/ws.py` (stub from RB-101; keep the
`router` name), `api/app/static/index.html` (replace RB-101's placeholder), and `api/tests/ws/**`
(CONTRACTS section 13). Never touch `app/main.py`.

## Required reading

1. `docs/CONTRACTS.md` sections 5 (WsPublisher, AgentService), 7 (routes), 8 (WS message
   protocol - implement VERBATIM both sides)
2. `docs/design.md` sections 6.7, 8 (grounding invariant - the UI renders quotes/status from
   structured messages, never from assistant prose), 9 (security headers)

## Scope

### 1. `app/ws/manager.py` - `ConnectionManager`

Implements `WsPublisher`. `dict[str, set[WebSocket]]` keyed by session_id (a session may have
multiple tabs), `asyncio.Lock` around mutation. `connect(session_id, ws)`, `disconnect(...)`,
`publish(session_id, message)`: send JSON to every socket of that session; a send failure
disconnects that socket silently; publishing to a session with no sockets is a no-op (contract).
`# ponytail: in-process connection registry, single instance; needs a pub/sub bus (SNS/redis) if api ever scales out`

### 2. `app/routers/ws.py` - WebSocket endpoint (fill the stub)

`@router.websocket("/ws")`: query param `session_id` must match UUID v4 regex
`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` (case-insensitive) else
close with code 4400. On accept: register with the manager, then receive-loop:
- parse JSON; must be `{"type": "user_msg", "text": <non-empty str, max 2000 chars>}` else send
  `{"type": "error", "message": "invalid message"}` and continue
- call `app.registry.get_agent_service().handle_user_message(session_id, text)` - fetch the
  service PER MESSAGE via the registry (RB-101's seam; RB-105 registers the real service - you
  never import `app.deps` or anything under `app/agent/`). If the registry raises RuntimeError
  (agent core not deployed yet), send `{"type": "error", "message": "assistant not available"}`.
On disconnect: deregister. Register your publisher at startup: in this module's lifespan/startup
hook call `app.registry.set_publisher(manager_singleton)` exactly once so RB-105's code publishes
through you.

### 3. `app/static/index.html` - the chat page (single file, vanilla JS + CSS, no build, no CDN)

Layout: message list, input box + Send, connection status dot. On load: get/create `session_id`
in `localStorage` (`crypto.randomUUID()`), open `ws://<host>/ws?session_id=...`, auto-reconnect
with 1s/2s/4s/8s backoff (status dot red while down).

Renderers per CONTRACTS section 8 (one function per message type; unknown types logged to
console, never rendered):
- `assistant_msg` / user echo: plain chat bubbles (textContent only - NEVER innerHTML with
  server/user strings; XSS is in scope even for an MVP)
- `quotes`: a card per quote: `product_name`, `price_display`, `pickup_eta_minutes` min pickup,
  `duration_minutes` min ride. No buttons (booking goes through the conversation; the model
  proposes, the card confirms)
- `confirmation_request`: highlighted card: action title ("Confirm booking" / "Confirm
  cancellation"), `summary.product_name`, `summary.price_display`, `summary.pickup_label` ->
  `summary.dropoff_label`, expiry countdown (from `summary.expires_at`; card auto-disables at
  zero with "Expired - ask again"). Buttons Confirm / Dismiss -> `POST /confirm`
  `{"token", "decision"}`; disable both buttons immediately on first click (client-side
  double-submit guard; the server-side claim is the real one)
- `confirmation_resolved`: mark the matching card (by token) as Booked / Dismissed / Expired /
  Failed
- `trip_update`: one persistent status card per trip_id (upsert by trip_id): status stepper
  `processing -> accepted -> arriving -> in_progress -> completed` (terminal branches shown as
  final state), driver name + rating when present, `product_name`, `price_display`
- `error`: red toast

### 4. Security: CSP meta tag

Response security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) are
already emitted by middleware in `main.py` (RB-101 owns that file). Your job is the in-page CSP:
add `<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'
'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:; img-src 'self'
data:">` (inline script/style must stay allowed because the page is a single self-contained
file).

## Out of scope

Agent logic, confirm endpoint internals (you only POST to it), storage, styling beyond clean and
readable (no framework, no fonts/CDN - self-contained file).

## Interfaces produced

- `ConnectionManager` registered as THE `WsPublisher` via `app.registry.set_publisher` at startup
- The `/ws` endpoint per CONTRACTS section 7
- The chat page at `/`

## Test plan (pytest; `TestClient` websocket support; `FakeAgentService` recording calls;
`app.deps.set_publisher` interplay tested with the real manager)

`tests/ws/test_manager.py`:
- `test_publish_to_connected_session` - fake WebSocket objects; message delivered to both tabs
  of the same session, not to another session
- `test_publish_no_connection_noop`
- `test_send_failure_evicts_socket`

`tests/ws/test_endpoint.py`:
- `test_invalid_session_id_rejected` - `session_id=not-a-uuid` -> close code 4400
- `test_user_msg_dispatched_to_agent_service` - connect with valid UUID, send user_msg, fake
  service (installed via `app.registry.set_agent_service(fake)`) received `(session_id, text)`
- `test_invalid_payload_gets_error_message` - send `{"type":"bogus"}` -> error message received,
  connection still open (send a valid message after and it dispatches)
- `test_oversize_text_rejected` - 2001 chars -> error message
- `test_agent_not_wired_reports_error` - reset registry to defaults; user_msg -> error
  "assistant not available", connection survives
- `test_publisher_wired` - after app startup, `app.registry.get_publisher()` is the manager, and
  a publish reaches a connected test client

`tests/ws/test_static_page.py`:
- `test_index_served_with_csp` - GET `/` contains `Content-Security-Policy` meta tag and the
  string `localStorage`
- `test_no_innerhtml_on_dynamic_content` - static grep: page source contains no `innerHTML`
  assignment (allowlist: zero occurrences; use textContent/createElement)

Manual verification (headed browser, document in close-out): open two tabs same session ->
messages mirror; kill api container -> dot goes red, reconnects on restart.

## Security checklist

- [ ] `textContent`/DOM-API rendering only; zero `innerHTML` with dynamic strings
- [ ] CSP meta tag present; page loads nothing from any external origin
- [ ] session_id validated server-side (regex above) before accept
- [ ] Input length capped (2000 chars) server-side

## Acceptance criteria

- [ ] All tests above pass (`cd api && python -m pytest tests/ws -v`; no LocalStack needed if
      your fakes cover the service - if you need repos, run in-container like RB-103)
- [ ] Page works end-to-end against a `FakeAgentService` wired via deps (manual check)
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters
- [ ] Only owned files created/modified

## Definition of done

All boxes checked; close-out note at the bottom of this file: what was built, deviations (owner
approval first), exact verify commands, screenshot-level description of the UI.
