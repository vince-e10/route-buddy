# Route Buddy

Route Buddy finds, compares, books, tracks, and cancels Singapore rides. The MVP uses a
deterministic mock of Uber Guest Rides, never the real Uber API.

```
                    docker compose up  (one command)
┌─────────────────────────────────────────────────────────────────┐
│  Browser ◀──(WebSocket: chat + confirms + live status)──┐       │
│  (static chat page served by api)                       ▼       │
│   ┌─────────┐ terraform apply  ┌──────────────────────────────┐ │
│   │  iac    │────────────────▶ │          api (FastAPI)       │ │
│   │ (init,  │                  │ agent loop · tools · gate    │ │
│   │ exits)  │                  │ action log · sessions · WS   │ │
│   └────┬────┘                  └───┬───────────┬──────────────┘ │
│        │ creates tables            │           ▲                │
│        ▼                           ▼           │ webhook        │
│   ┌────────────┐             ┌────────────┐    │ (status_changed│
│   │   floci    │◀────────────│ mock-uber  │────┘  + shared     │
│   │ DynamoDB   │  (no - api  │ (FastAPI)  │       secret)      │
│   │ 4 tables   │  only)      │ Guest Rides│                    │
│   └────────────┘             │ + driver   │                    │
│                              │   simulator│                    │
│                              └────────────┘                    │
└───────────────────────┬─────────────────────┬───────────────────┘
                        ▼ external            ▼ external
                  OpenRouter API         SG OneMap API
             (glm-4.5-air → minimax-m2)  (geocoding, token)
```

## Prerequisites and environment

Install Docker Desktop with Compose v2. Copy `.env.example` to `.env`; it is gitignored. Do not
commit values or put secrets in chat. The local mock works with the documented mock defaults;
real OpenRouter and OneMap values are needed for the non-fake demo path.

| Variable | Obtain or set it from |
| --- | --- |
| `OPENROUTER_API_KEY` | An [OpenRouter API key](https://openrouter.ai/keys). |
| `OPENROUTER_BASE_URL` | The documented OpenRouter base URL in `.env.example`. |
| `OPENROUTER_MODEL_PRIMARY` | The approved primary model in `.env.example`. |
| `OPENROUTER_MODEL_FALLBACK` | The approved fallback model in `.env.example`. |
| `LLM_MODE` | `openrouter` for normal use or `fake` for deterministic tests. |
| `FLOCI_STORAGE_MODE` | `persistent` locally or `memory` for disposable CI runs. |
| `FLOCI_STORAGE_PERSISTENT_PATH` | The documented Floci container path in `.env.example`. |
| `AWS_ENDPOINT_URL` | The Compose Floci endpoint in `.env.example`. |
| `AWS_ACCESS_KEY_ID` | The local Floci test credential in `.env.example`. |
| `AWS_SECRET_ACCESS_KEY` | The local Floci test credential in `.env.example`. |
| `AWS_DEFAULT_REGION` | The Singapore region in `.env.example`. |
| `UBER_BASE_URL` | The Compose mock-Uber endpoint in `.env.example`. |
| `UBER_API_TOKEN` | The static MVP mock token in `.env.example`. |
| `UBER_ORG_UUID` | The static MVP mock organization id in `.env.example`. |
| `WEBHOOK_SHARED_SECRET` | A locally generated secret used by API and mock-Uber only. |
| `ONEMAP_BASE_URL` | The OneMap API base URL in `.env.example`. |
| `ONEMAP_EMAIL` | The email for your [OneMap account](https://www.onemap.gov.sg/home/). |
| `ONEMAP_PASSWORD` | The password for that OneMap account. |
| `RIDER_FIRST_NAME` | The local MVP rider's first name. |
| `RIDER_LAST_NAME` | The local MVP rider's last name. |
| `RIDER_PHONE` | The local MVP rider's E.164 phone number. |
| `SIM_SPEED` | Lifecycle speed multiplier; keep the documented default unless demoing. |
| `MOCK_DETERMINISTIC` | `1` for deterministic tests, otherwise `0`. |
| `WEBHOOK_TARGET_URL` | The Compose API webhook URL in `.env.example`. |

## Run and demo

```sh
cp .env.example .env
# Edit .env locally with the values above.
docker compose up -d --build
```

Open `http://localhost:8000`, or use the bounded startup helper:

```sh
./scripts/demo.sh
```

Example conversation:

1. `Take me from Changi Airport to Marina Bay Sands`
2. `book UberX`, then click Confirm on the exact booking card.
3. `cancel that one`, then click Confirm on the exact cancellation card.

## Tests

The release gate starts a disposable deterministic stack, runs all API, live WebSocket, security,
and mock-Uber tests, then always removes containers and volumes.

```sh
./scripts/e2e.sh
```

For focused checks against an already running stack:

```sh
docker compose exec -T api python -m pytest tests -v
docker compose run --rm --no-deps -v "$PWD/mock-uber/tests:/tests:ro" mock-uber python -m pytest /tests -v
```

## Architecture and invariants

- Every book or cancel requires a fresh, single-use user confirmation.
- The DynamoDB action log is append-only and records requested, verified, executed, and outcome phases.
- Prices, ETAs, identifiers, and lifecycle state come from tool output, never model invention.
- The model never receives rider PII. The API adds it only while executing a confirmed booking.

## Known MVP limitations

1. Floci is a development emulator, not proof of real AWS durability, scaling, IAM, or service
   limits. Production validation still runs against AWS.
2. Webhook auth is a shared secret, not signatures - prod item
3. Single region/market (SG), single user, English-first prompts
4. Model may occasionally produce a malformed tool call despite mitigations - the failure mode is a logged refusal and a re-ask, never an unintended action (the gate guarantees this)

## Docs

- [Requirements](docs/high-level-requirements.md)
- [Approved design](docs/design.md)
- [Frozen contracts](docs/contracts.md)
- [Execution plan](docs/execution-plan.md)
- [Live RFC status](docs/rfc.md)
