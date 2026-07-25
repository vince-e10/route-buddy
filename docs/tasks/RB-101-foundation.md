# RB-101: Foundation - compose stack, Terraform IaC, service skeletons, shared models

| Field | Value |
|---|---|
| Type | Task |
| Wave | 1 (must complete before all other tickets) |
| Depends on | none |
| Blocks | RB-102, RB-103, RB-104, RB-105, RB-106, RB-107 |
| Size | M |

## Context

Route Buddy (see `docs/design.md`, sections 5, 6.6, 9) is a 3-runtime-container system: `api`
(FastAPI orchestrator + static chat UI), `mock-uber` (Uber Guest Rides mock), `localstack`
(DynamoDB), plus a short-lived `iac` container that applies Terraform and exits. This ticket builds
the skeleton everything else plugs into: compose file, Terraform data module, Dockerfiles, config
loading, the shared Pydantic models, the seam protocols, stub routers, and the PII/secret log
redaction filter. Later tickets fill in behavior; they must never need to touch your files again
(see the file ownership map, `docs/CONTRACTS.md` section 13).

## Required reading (before writing any code)

1. `docs/CONTRACTS.md` - ALL sections; you implement sections 1-5 and 13 verbatim
2. `docs/design.md` sections 5 (architecture), 6.6 (IaC), 9 (security)
3. `AGENTS.md` (repo conventions; note: NOT a git repo - no git commands)

## Scope

1. **`docker-compose.yml`** - services `localstack`, `iac`, `mock-uber`, `api` per CONTRACTS
   section 1: ports, healthchecks, `depends_on` conditions exactly as specified. All services read
   env from `.env` (compose `env_file`). Only `api` publishes a host port (8000). LocalStack needs
   `LOCALSTACK_AUTH_TOKEN` passed through and a healthcheck on `/_localstack/health`.
2. **`.env.example`** - exact content of CONTRACTS section 2. Empty values for secrets. Also create
   the compose setup so a missing `.env` fails fast with a clear error (document in file header
   comment: `cp .env.example .env` first).
3. **Terraform** (`infra/`):
   - `infra/modules/data/main.tf` (+ `variables.tf`): the 4 DynamoDB tables from CONTRACTS
     section 3 - names, keys, GSI `by_session` on `trips`, TTL on `sessions.expires_at` and
     `pending_actions.expires_at`, `PAY_PER_REQUEST`.
   - `infra/local/main.tf` + `infra/local/providers.tf`: instantiates the module against
     LocalStack. Use the plain `hashicorp/terraform` image with an AWS provider `endpoints` block
     pointing every used service at `http://localstack:4566`, plus
     `skip_credentials_validation = true`, `skip_metadata_api_check = true`,
     `skip_requesting_account_id = true`, `s3_use_path_style = true`, static test credentials,
     region `ap-southeast-1`. (This is the design's "tflocal" intent implemented directly with an
     endpoints block - no wrapper dependency.)
   - `iac` compose service: `hashicorp/terraform:1.9` image, mounts `infra/`, working dir
     `/infra/local`, entrypoint runs `terraform init -input=false && terraform apply -input=false
     -auto-approve`. State stays inside the container (ephemeral BY DESIGN - every compose up is a
     clean apply against a fresh LocalStack; do NOT mount a state volume).
4. **api skeleton** (`api/`):
   - `Dockerfile`: `python:3.12-slim`, non-root user (`useradd -m app` + `USER app`), installs
     pinned `requirements.txt`, runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
   - `requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`, `boto3`, `pytest`,
     `pytest-asyncio`, `respx` - pin EXACT current stable versions (`==`) at implementation time.
   - `.dockerignore`: `.env`, `__pycache__/`, `*.pyc`, `tests/`, `.pytest_cache/`.
   - `app/config.py`: a pydantic-settings (or plain os.environ) `Settings` class exposing every
     env var from CONTRACTS section 2 as a typed attribute; loaded once, injected everywhere.
     List `SECRET_ENV_VARS = ["OPENROUTER_API_KEY", "LOCALSTACK_AUTH_TOKEN",
     "WEBHOOK_SHARED_SECRET", "ONEMAP_EMAIL", "ONEMAP_PASSWORD"]`.
   - `app/models.py`: CONTRACTS section 4, VERBATIM (models, `LEGAL_TRANSITIONS`,
     `CANCELLABLE_STATUSES`).
   - `app/providers/base.py`, `app/geocode/base.py`, `app/ws/publisher.py`: CONTRACTS section 5
     protocols, verbatim.
   - `app/registry.py`: the wiring seam per CONTRACTS section 5 - module-level
     `set_publisher`/`get_publisher` (default: a `NoopPublisher` whose `publish` does nothing)
     and `set_agent_service`/`get_agent_service` (default: raise
     `RuntimeError("agent service not wired")`). This is what lets RB-105 and RB-106 build in
     parallel without sharing files.
   - `app/routers/confirm.py`, `app/routers/webhooks.py`, `app/routers/ws.py`: each defines an
     empty `router = APIRouter()` (stub; filled by RB-105/RB-106 - leave a one-line comment naming
     the owning ticket).
   - `app/main.py`: creates the FastAPI app, includes all three routers, mounts
     `app/static/` at `/` (create the dir with a placeholder `index.html` saying "Route Buddy - UI
     arrives in RB-106"), adds `GET /healthz` -> `{"status":"ok"}`, installs logging on startup,
     and registers a small security-headers middleware adding `X-Content-Type-Options: nosniff`,
     `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` to every response. In the startup
     hook, attempt `import app.deps` inside `try/except ImportError` with a warning log on the
     except path (deps.py arrives in RB-105 and self-registers via `app.registry`; the api must
     boot at every wave). Written ONCE here; no later ticket edits it.
   - `app/logging_setup.py`: structured JSON logging to stdout with a **redaction filter** applied
     to the root logger: (a) regex masking of phone numbers (`\+\d{7,15}` and SG local
     `\b[689]\d{7}\b`) and emails (`[\w.+-]+@[\w-]+\.[\w.]+`), replaced with `[REDACTED]`;
     (b) exact-substring masking of the VALUES of every var in `SECRET_ENV_VARS` that is non-empty.
     The filter must mask inside formatted message strings and inside `extra` dict values.
5. **mock-uber skeleton** (`mock-uber/`): `Dockerfile` (same pattern, port 8001, non-root),
   `requirements.txt` (`fastapi`, `uvicorn[standard]`, `pydantic`, `httpx`, `pytest`,
   `pytest-asyncio` - pinned), `.dockerignore`, `app/main.py` with `GET /healthz` ->
   `{"status":"ok"}` only (RB-102 replaces the internals; keep `app/` a package).

## Out of scope

Any business logic, storage code, agent code, real UI, mock-uber endpoints beyond healthz.

## Interfaces produced (later tickets rely on these EXACTLY)

- `app.config.Settings` with attributes named after CONTRACTS section 2 vars (lowercased)
- `app.models.*` per CONTRACTS section 4
- Protocols per CONTRACTS section 5
- `app.registry` accessors per CONTRACTS section 5 (RB-105 registers the agent service, RB-106
  registers the publisher; both only consume this wave-1 artifact)
- Stub routers importable as `app.routers.confirm.router`, `app.routers.webhooks.router`,
  `app.routers.ws.router`
- Compose service names `api`, `mock-uber`, `localstack`, `iac` (in-network DNS names)

## Test plan (write tests first where practical)

`api/tests/test_health.py`:
- `test_healthz` - `TestClient(app).get("/healthz")` returns 200 `{"status":"ok"}`
- `test_static_index_served` - `GET /` returns 200 and contains "Route Buddy"

`api/tests/test_logging.py`:
- `test_redacts_phone` - log `"call +6591234567 now"`, captured stdout record contains
  `[REDACTED]`, not the number
- `test_redacts_sg_local_phone` - `"call 91234567"` masked
- `test_redacts_email` - `"mail a.b+c@example.com"` masked
- `test_redacts_secret_value` - with `WEBHOOK_SHARED_SECRET=supersecret123` set, logging a string
  containing `supersecret123` masks it
- `test_normal_text_untouched` - `"quote SGD 15.50 for UberX"` passes through unchanged

`api/tests/test_registry.py`:
- `test_default_publisher_is_noop` - `get_publisher().publish("x", {})` returns without error
- `test_default_agent_service_raises` - `get_agent_service()` raises RuntimeError
- `test_set_then_get_roundtrip` - for both accessors

Manual verification (document commands in the ticket close-out note):
- `cp .env.example .env` (fill `LOCALSTACK_AUTH_TOKEN`), `docker compose up -d --build`; then
  `docker compose ps` shows `iac` exited 0, `api` + `mock-uber` + `localstack` healthy/running
- `curl -s localhost:8000/healthz` -> `{"status":"ok"}`
- `docker compose exec localstack awslocal dynamodb list-tables` returns all 4 tables
- `docker compose down && docker compose up -d` works again (idempotent clean apply)

## Security checklist

- [ ] Containers run as non-root
- [ ] `.dockerignore` excludes `.env` in both services
- [ ] No secret value appears in any Dockerfile, compose file, or Terraform file
- [ ] Redaction filter tests pass
- [ ] Only `api` maps a host port

## Acceptance criteria

- [ ] `docker compose up -d --build` from a clean checkout (with `.env` present) reaches: iac
      exited 0, all 4 DynamoDB tables exist, api healthz 200, mock-uber healthz 200 in-network
- [ ] Restart cycle (`down` then `up -d`) succeeds without manual steps
- [ ] All pytest tests above pass (`cd api && python -m pytest tests/ -v`)
- [ ] Files match the ownership map (CONTRACTS section 13) - nothing extra, nothing missing
- [ ] Every file ends with exactly one trailing newline; no em/en-dash characters anywhere

## Definition of done

All acceptance boxes checked; close-out note written at the bottom of this file listing: what was
built, exact versions pinned, any deviation from spec (deviations require owner approval FIRST).
