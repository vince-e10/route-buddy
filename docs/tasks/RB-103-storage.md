# RB-103: Storage layer - DynamoDB repositories (sessions, trips, action log, pending actions)

| Field | Value |
|---|---|
| Type | Task |
| Wave | 2 (parallel with RB-102, RB-104) |
| Depends on | RB-101 |
| Blocks | RB-105, RB-106, RB-107 |
| Size | M |

## Context

All persistent state lives in 4 DynamoDB tables (created by RB-101's Terraform; schema in
CONTRACTS section 3). This ticket implements the repository classes that are the ONLY code in the
system allowed to touch DynamoDB. Two of them carry system invariants: `ActionLogRepo` is
append-only (the audit trail - design.md 6.3), and `PendingActionRepo.claim` is the atomic
single-use mechanism under the confirmation gate (design.md 6.2) - a double-click on Confirm must
never double-book, and that guarantee lives HERE, in a conditional write.

You own `api/app/storage/**` and `api/tests/storage/**` only (CONTRACTS section 13).

## Required reading

1. `docs/CONTRACTS.md` sections 3 (tables + ID conventions), 4 (models - already implemented in
   `api/app/models.py` by RB-101; import from there, do not redefine), 5 (your class signatures,
   VERBATIM)
2. `docs/design.md` sections 6.3 (action log) and 6.5 (data model)

## Scope

Create `api/app/storage/` with one module per repository plus `__init__.py` exporting all four.
Use `boto3` (sync client is fine wrapped with `asyncio.to_thread`, or use `aioboto3` if you
prefer - pick ONE and note it; do not add both). boto3 picks up `AWS_ENDPOINT_URL` from env
automatically - construct clients with NO explicit `endpoint_url` argument (that is the
local-vs-prod switch; design.md 3.2).

1. **`session_repo.py` - `SessionRepo`**
   - `get(session_id)` -> `Session | None`. Returns None if item absent OR `expires_at <= now`
     (code-side expiry; DynamoDB TTL is lazy).
   - `put(session)` -> stores with `expires_at = int(now + 24h)`, `updated_at = now`. Enforce
     caps before write: `messages` max 40 (drop oldest), `places` max 20 (drop oldest inserted;
     dicts preserve insertion order).
   - Serialize nested models via `model_dump(mode="json")`; datetimes as ISO strings; floats as
     `Decimal` where DynamoDB requires (write a tiny `_to_ddb`/`_from_ddb` helper pair and unit
     test round-tripping).
2. **`trip_repo.py` - `TripRepo`**
   - `put(trip)`, `get(trip_id)`, `list_by_session(session_id)` (query GSI `by_session`,
     sort result by `created_at` ascending in code).
   - `apply_status_event(trip_id, event_id, new_status, driver)` -> `Trip | None`:
     single `UpdateItem` with
     `ConditionExpression="attribute_exists(trip_id) AND (attribute_not_exists(last_event_id) OR last_event_id <> :eid)"`,
     setting `status`, `last_event_id`, `updated_at`, and `driver` (only if driver arg non-null).
     BEFORE the update, `get` the trip and check `new_status in LEGAL_TRANSITIONS[current.status]`;
     illegal -> return None (log at warning). On `ConditionalCheckFailedException` (duplicate
     event or missing trip) -> return None. On success return the updated `Trip`.
     Note the read-then-write gap is acceptable here: the mock emits events strictly in order and
     the condition on `last_event_id` catches straight duplicates; add
     `# ponytail: read-then-check transition, single-writer webhook path; move check into the condition expression if providers ever race`.
3. **`action_log_repo.py` - `ActionLogRepo`**
   - `append(entry)` is the ONLY public method - no get/update/delete/scan methods exist on this
     class at all (append-only by construction). `entry_key` is assigned HERE per CONTRACTS
     section 3 if the caller left it empty.
4. **`pending_action_repo.py` - `PendingActionRepo`**
   - `put(action)`.
   - `claim(token)` -> `PendingAction | None`: `DeleteItem` with
     `ConditionExpression="attribute_exists(#t)"` and `ReturnValues="ALL_OLD"`; on
     `ConditionalCheckFailedException` return None. Then, in code, if
     `old_item.expires_at <= now` return None (expired-but-not-yet-TTL-swept). Exactly one caller
     of two concurrent `claim(token)` calls can receive the action - this is the invariant.

## Out of scope

Business logic, HTTP anything, table creation (Terraform owns it), caching.

## Interfaces produced (RB-105/106/107 rely on these exactly)

The four classes with signatures per CONTRACTS section 5, importable as
`from app.storage import SessionRepo, TripRepo, ActionLogRepo, PendingActionRepo`, each
constructed with no arguments (they read table names as constants and boto3 config from env).

## Test plan

Tests run against real LocalStack DynamoDB (matches design: no moto, one emulator for everything).
Test bootstrap: `docker compose up -d localstack iac` first; tests read `AWS_ENDPOINT_URL`
(document `AWS_ENDPOINT_URL=http://localhost:4566` + port note below). Compose maps no host port
for localstack, so tests run INSIDE the api container:
`docker compose run --rm --no-deps -e AWS_ENDPOINT_URL=http://localstack:4566 api python -m pytest tests/storage -v`
(document this exact command in the close-out note). Each test uses a fresh `session_id`/ids
(uuid4) so tests are order-independent.

`tests/storage/test_session_repo.py`:
- `test_roundtrip` - put then get returns an equal `Session` (nested Quote/Place survive,
  datetimes intact)
- `test_absent_returns_none`
- `test_code_expiry` - put a session, manually rewrite its `expires_at` to now-10 via raw boto3
  in the test, get -> None
- `test_message_cap` - put with 45 messages -> get returns the LAST 40
- `test_places_cap` - 25 places -> last 20 kept

`tests/storage/test_trip_repo.py`:
- `test_put_get_roundtrip`
- `test_list_by_session_ordered` - 3 trips, distinct created_at -> ascending order
- `test_apply_event_happy` - trip in `processing`, event -> `accepted` returns updated trip with
  `last_event_id` set and driver stored
- `test_apply_event_duplicate` - same `event_id` twice -> second call returns None, status
  unchanged
- `test_apply_event_illegal_transition` - `completed` -> `accepted` returns None
- `test_apply_event_unknown_trip` - returns None

`tests/storage/test_action_log_repo.py`:
- `test_append_and_read_back_raw` - append 3 entries (same session), read back with RAW boto3
  query in the test (the repo itself has no read method - assert that too via
  `not hasattr(repo, "get")`), entries in entry_key order with all fields intact
- `test_append_only_surface` - `[m for m in dir(repo) if not m.startswith("_")] == ["append"]`

`tests/storage/test_pending_action_repo.py`:
- `test_put_claim_roundtrip` - claim returns the action with payload intact
- `test_claim_twice` - second claim returns None
- `test_claim_absent` - None
- `test_claim_expired` - put with `expires_at = now - 5`, claim -> None
- `test_concurrent_claim_single_winner` - `asyncio.gather` of 10 concurrent claims on one token:
  exactly 1 non-None result

## Security checklist

- [ ] No PII or secret values in log lines emitted by repositories (log ids and outcomes only)
- [ ] No `endpoint_url` hardcoded anywhere (env-driven only)

## Acceptance criteria

- [ ] All tests pass with the documented in-container command against LocalStack
- [ ] `ActionLogRepo` exposes `append` and nothing else
- [ ] Concurrency test proves single-winner claim
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters
- [ ] Only files under `api/app/storage/**` and `api/tests/storage/**` created/modified

## Definition of done

All boxes checked; close-out note at the bottom of this file: what was built, boto3 vs aioboto3
choice, deviations (owner approval first), exact verify commands.
