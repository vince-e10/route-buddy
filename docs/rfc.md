# Route Buddy - Live RFC

_Repos touched:_ [vince-e10/route-buddy](https://github.com/vince-e10/route-buddy)
_Issues:_ [RB-100 #10](https://github.com/vince-e10/route-buddy/issues/10), plus
[RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2) through
[RB-107 #8](https://github.com/vince-e10/route-buddy/issues/8)
_Docs:_ all project docs live in this `docs/` folder alongside the code (owner decision
2026-07-25, overriding the docs-in-vault convention): `high-level-requirements.md` (spec),
`design.md` (approved RFC), `contracts.md` (normative interfaces), `execution-plan.md` (delivery),
this file (live status).

## Current State
_Last updated: 2026-07-25_

**Goal:** AI agent that books and manages ride-hailing trips end to end (SG market, mocked Uber Guest Rides provider, FastAPI, DynamoDB on an AWS-compatible local emulator, Terraform IaC), with structurally enforced confirmation gate, append-only action log, and grounded answers.
**Status:** Repository initialized; planning PRs [#1](https://github.com/vince-e10/route-buddy/pull/1) and [#9](https://github.com/vince-e10/route-buddy/pull/9) merged. RB-100 passed, validating pinned Floci 1.5.33 for local DynamoDB and Terraform; the decision PR is pending merge. Eight tracked issues cover the gate and implementation. No application code yet.
**Next step:** Merge the RB-100 decision PR, then implement [RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2).
**Open questions:**
- OneMap token refresh flow (token registered, ~3-day expiry) - implementor task, not a blocker
- Action-log retention policy - production decision
- Uber partner approval timeline - business, needed only for real-provider swap

## Log

### 2026-07-25 - Floci compatibility gate passed
- [RB-100](https://github.com/vince-e10/route-buddy/issues/10) passed against `floci/floci:1.5.33`
  (digest `sha256:d2ecc8035822b23b8587a56eab15edd825f41d3fb80d93e8e66680410beddc08`).
- The [evidence](https://github.com/vince-e10/route-buddy/issues/10#issuecomment-5078441200)
  records Terraform 1.9.8 with AWS provider 6.56.0, exact schemas and TTLs, GSI pagination,
  Decimal round trips, conditional-write concurrency, duplicate-event rejection, persistent
  restart/recreation with a no-op re-apply, destroy, and clean memory-mode recreation.
- Decision: use pinned Floci 1.5.33 for local development and CI. Keep the production module
  emulator-neutral and validate it against real AWS before production.

### 2026-07-25 - Floci compatibility gate added
- Selected `floci/floci:1.5.33` provisionally to remove LocalStack account-token, licensing, persistence, and CI-secret friction.
- Added [RB-100 #10](https://github.com/vince-e10/route-buddy/issues/10) as a hard gate before RB-101. It tests the exact Terraform lifecycle, DynamoDB condition expressions, pagination, TTL configuration, persistent restart, and memory-only CI workflow.
- Defined the failure path: use official DynamoDB Local for the MVP and update the decision records before implementation.
- Standardized project-owned document names on lowercase kebab-case and renamed `docs/CONTRACTS.md` to `docs/contracts.md`. Conventional tool-recognized names remain unchanged.

### 2026-07-25 - Implementation tracking moved to GitHub Issues
- Migrated RB-101 through RB-107 into [GitHub Issues](https://github.com/vince-e10/route-buddy/issues).
- GitHub Issues are now the execution source of truth; design and frozen contracts remain versioned in the repository.
- Removed the duplicate local task files and updated the delivery workflow to feature branches and pull requests against `main`.

### 2026-07-25 - Repository initialized and scaffold PR opened
- Initialized the Git repository, connected it to `vince-e10/route-buddy`, and published the planning scaffold in [PR #1](https://github.com/vince-e10/route-buddy/pull/1).
- Configured local Git authorship for `vince-e10` and GitHub CLI access for PR operations.

### 2026-07-25 - Execution plan + issue set written
- Broke the design into 7 agent-delegatable issues in 4 waves: RB-101 foundation -> RB-102/103/104 (mock-uber, storage, adapters, parallel) -> RB-105/106 (agent core + gate, WS + UI, parallel) -> RB-107 (live integration, e2e, security verification, README).
- All cross-issue interfaces frozen in `docs/contracts.md` (normative): models, protocols, tool schemas, WS protocol, mock-uber response shapes, table schemas, env vars, file ownership map.
- Parallelism inside a wave is safe by disjoint file ownership; RB-105/RB-106 decoupled via an `app.registry` seam built in wave 1.
- Plan-review (reviewer-pragmatic) found 6 issues, all fixed: registry seam replacing a deps.py collision, two literal spec bugs in RB-105 (datetime->epoch, contradictory webhook driver instruction), /confirm response shape, rate-limit wording, ownership-map annotation, CORS verification line; plus a poll-reconciliation edge case fixed via trip_repo.put.

### 2026-07-25 - Design approved, RFC written
- Researched (3 parallel agents): Uber API access reality, LocalStack 2026 state, OpenRouter tool-calling models.
- Key decisions: mock Guest Rides provider (real API is partner-gated, no self-serve sandbox); OpenRouter glm-4.5-air primary + minimax-m2 fallback; DynamoDB via LocalStack free tier (RDS/Secrets Manager are paid there); Terraform + tflocal from day 1 (ephemeral local tfstate); OneMap geocoding behind a Geocoder seam; WebSocket UI transport; no SQS/scheduled rides in MVP.
- Security addendum after Vincent's requirement: LLM never sees PII (guest identity attached server-side at confirm-execution), two-stream log hygiene with redaction, secrets only via .env/Secrets Manager, prompt-injection defense = the confirm gate.
- Two plan-review passes ran (base design + security addendum); all findings accepted and folded in.
- Full design: [[design]].
