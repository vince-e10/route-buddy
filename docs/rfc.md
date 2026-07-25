# Route Buddy - Live RFC

_Repos touched:_ [vince-e10/route-buddy](https://github.com/vince-e10/route-buddy)
_Issues:_ [RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2) through
[RB-107 #8](https://github.com/vince-e10/route-buddy/issues/8)
_Docs:_ all project docs live in this `docs/` folder alongside the code (owner decision
2026-07-25, overriding the docs-in-vault convention): `high-level-requirements.md` (spec),
`design.md` (approved RFC), this file (live status).

## Current State
_Last updated: 2026-07-25_

**Goal:** AI agent that books and manages ride-hailing trips end to end (SG market, mocked Uber Guest Rides provider, FastAPI, LocalStack->AWS, Terraform IaC), with structurally enforced confirmation gate, append-only action log, and grounded answers.
**Status:** Repository initialized and [PR #1](https://github.com/vince-e10/route-buddy/pull/1) merged. Design and contracts are approved. All seven implementation tasks are tracked as GitHub issues with acceptance criteria and dependencies. No application code yet.
**Next step:** Implement [RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2), verify the compose skeleton, then continue through waves 2-4.
**Open questions:**
- OneMap token refresh flow (token registered, ~3-day expiry) - implementor task, not a blocker
- Action-log retention policy - production decision
- Uber partner approval timeline - business, needed only for real-provider swap

## Log

### 2026-07-25 - Implementation tracking moved to GitHub Issues
- Migrated RB-101 through RB-107 into [GitHub Issues](https://github.com/vince-e10/route-buddy/issues).
- GitHub Issues are now the execution source of truth; design and frozen contracts remain versioned in the repository.
- Removed the duplicate local task files and updated the delivery workflow to feature branches and pull requests against `main`.

### 2026-07-25 - Repository initialized and scaffold PR opened
- Initialized the Git repository, connected it to `vince-e10/route-buddy`, and published the planning scaffold in [PR #1](https://github.com/vince-e10/route-buddy/pull/1).
- Configured local Git authorship for `vince-e10` and GitHub CLI access for PR operations.

### 2026-07-25 - Execution plan + issue set written
- Broke the design into 7 agent-delegatable issues in 4 waves: RB-101 foundation -> RB-102/103/104 (mock-uber, storage, adapters, parallel) -> RB-105/106 (agent core + gate, WS + UI, parallel) -> RB-107 (live integration, e2e, security verification, README).
- All cross-issue interfaces frozen in `docs/CONTRACTS.md` (normative): models, protocols, tool schemas, WS protocol, mock-uber response shapes, table schemas, env vars, file ownership map.
- Parallelism inside a wave is safe by disjoint file ownership; RB-105/RB-106 decoupled via an `app.registry` seam built in wave 1.
- Plan-review (reviewer-pragmatic) found 6 issues, all fixed: registry seam replacing a deps.py collision, two literal spec bugs in RB-105 (datetime->epoch, contradictory webhook driver instruction), /confirm response shape, rate-limit wording, ownership-map annotation, CORS verification line; plus a poll-reconciliation edge case fixed via trip_repo.put.

### 2026-07-25 - Design approved, RFC written
- Researched (3 parallel agents): Uber API access reality, LocalStack 2026 state, OpenRouter tool-calling models.
- Key decisions: mock Guest Rides provider (real API is partner-gated, no self-serve sandbox); OpenRouter glm-4.5-air primary + minimax-m2 fallback; DynamoDB via LocalStack free tier (RDS/Secrets Manager are paid there); Terraform + tflocal from day 1 (ephemeral local tfstate); OneMap geocoding behind a Geocoder seam; WebSocket UI transport; no SQS/scheduled rides in MVP.
- Security addendum after Vincent's requirement: LLM never sees PII (guest identity attached server-side at confirm-execution), two-stream log hygiene with redaction, secrets only via .env/Secrets Manager, prompt-injection defense = the confirm gate.
- Two plan-review passes ran (base design + security addendum); all findings accepted and folded in.
- Full design: [[design]].
