# Route Buddy - Live RFC

_Repos touched:_ route-buddy (vault folder, deliberately not a git repo yet)
_Ticket(s):_ none
_Docs:_ all project docs live in this `docs/` folder alongside the code (owner decision
2026-07-25, overriding the docs-in-vault convention): `high-level-requirements.md` (spec),
`design.md` (approved RFC), this file (live status).

## Current State
_Last updated: 2026-07-25_

**Goal:** AI agent that books and manages ride-hailing trips end to end (SG market, mocked Uber Guest Rides provider, FastAPI, LocalStack->AWS, Terraform IaC), with structurally enforced confirmation gate, append-only action log, and grounded answers.
**Status:** Design approved; execution plan + 7 delegatable tickets written and plan-reviewed ([[execution-plan]], `docs/tasks/RB-101..107`, contracts frozen in [[CONTRACTS]]). No code yet.
**Next step:** Dispatch RB-101 (wave 1 foundation) to an implementation agent, verify compose skeleton, then waves 2-4 per the execution plan.
**Open questions:**
- OneMap token refresh flow (token registered, ~3-day expiry) - implementor task, not a blocker
- Action-log retention policy - production decision
- Uber partner approval timeline - business, needed only for real-provider swap

## Log

### 2026-07-25 - Execution plan + ticket set written
- Broke the design into 7 agent-delegatable tickets in 4 waves: RB-101 foundation -> RB-102/103/104 (mock-uber, storage, adapters, parallel) -> RB-105/106 (agent core + gate, WS + UI, parallel) -> RB-107 (live integration, e2e, security verification, README).
- All cross-ticket interfaces frozen in `docs/CONTRACTS.md` (normative): models, protocols, tool schemas, WS protocol, mock-uber response shapes, table schemas, env vars, file ownership map.
- Parallelism inside a wave is safe by disjoint file ownership; RB-105/RB-106 decoupled via an `app.registry` seam built in wave 1.
- Plan-review (reviewer-pragmatic) found 6 issues, all fixed: registry seam replacing a deps.py collision, two literal spec bugs in RB-105 (datetime->epoch, contradictory webhook driver instruction), /confirm response shape, rate-limit wording, ownership-map annotation, CORS verification line; plus a poll-reconciliation edge case fixed via trip_repo.put.

### 2026-07-25 - Design approved, RFC written
- Researched (3 parallel agents): Uber API access reality, LocalStack 2026 state, OpenRouter tool-calling models.
- Key decisions: mock Guest Rides provider (real API is partner-gated, no self-serve sandbox); OpenRouter glm-4.5-air primary + minimax-m2 fallback; DynamoDB via LocalStack free tier (RDS/Secrets Manager are paid there); Terraform + tflocal from day 1 (ephemeral local tfstate); OneMap geocoding behind a Geocoder seam; WebSocket UI transport; no SQS/scheduled rides in MVP.
- Security addendum after Vincent's requirement: LLM never sees PII (guest identity attached server-side at confirm-execution), two-stream log hygiene with redaction, secrets only via .env/Secrets Manager, prompt-injection defense = the confirm gate.
- Two plan-review passes ran (base design + security addendum); all findings accepted and folded in.
- Full design: [[design]].
