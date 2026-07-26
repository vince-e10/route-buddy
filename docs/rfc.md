# Route Buddy - Live RFC

_Repos touched:_ [vince-e10/route-buddy](https://github.com/vince-e10/route-buddy)
_Issues:_ [RB-100 #10](https://github.com/vince-e10/route-buddy/issues/10), plus
[RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2) through
[RB-107 #8](https://github.com/vince-e10/route-buddy/issues/8), and post-MVP reliability work
[RB-108 #20](https://github.com/vince-e10/route-buddy/issues/20) through
[RB-110 #22](https://github.com/vince-e10/route-buddy/issues/22)
_Docs:_ all project docs live in this `docs/` folder alongside the code (owner decision
2026-07-25, overriding the docs-in-vault convention): `high-level-requirements.md` (spec),
`design.md` (approved RFC), `contracts.md` (normative interfaces), `execution-plan.md` (delivery),
this file (live status).

## Current State
_Last updated: 2026-07-26_

**Goal:** AI agent that books and manages ride-hailing trips end to end (SG market, mocked Uber Guest Rides provider, FastAPI, DynamoDB on an AWS-compatible local emulator, Terraform IaC), with structurally enforced confirmation gate, append-only action log, and grounded answers.
**Status:** MVP implemented. RB-108 adds a no-dispatch, repeatable live-model reliability
evaluation covering 34 synthetic cases, including 14 write turns and six recovery cases. Its
first baseline is partial: the configured Nemotron free route returned HTTP 404, and the
configured Gemma free route returned HTTP 429. Each non-retryable route stopped after its first
request. No model response, token usage, cost, or tool dispatch occurred.
**Next step:** Merge the RB-108 harness, rerun the identical fixture when the configured
OpenRouter routes are available, then use the completed baseline for RB-109 hardening.
**Open questions:**
- OneMap token refresh flow (token registered, ~3-day expiry) - implementor task, not a blocker
- Action-log retention policy - production decision
- Uber partner approval timeline - business, needed only for real-provider swap
- Free-model evaluation availability - Nemotron currently has no usable configured route and
  Gemma is rate limited; this is provider/quota behavior, not measured model quality

## Log

### 2026-07-26 - RB-108 reliability harness and partial live baseline
- Added a committed 34-case golden set and an offline-tested evaluator that pins one model,
  uses production request construction and tool validation, never dispatches a tool, and records
  structural, semantic, write, recovery, latency, token, and cost metrics.
- Requested three passes for each configured model. The retained partial report stopped Nemotron
  on its first HTTP 404 and Gemma on its first HTTP 429. Total tokens and observed cost were zero.
- Decision: do not attribute the result to model intelligence and do not activate deterministic
  write selection from transport failures. Complete the same baseline before RB-109 changes.

### 2026-07-26 - RB-107 integration release gate completed
- Added two cold deterministic Compose release-gate runs for API, mock-Uber, live WebSocket, and
  security tests; each run tears down containers and volumes.
- Verified search, quote, confirm-book, lifecycle updates, dismiss, cancel, no-driver, token
  replay, audit-log, and phone-redaction behavior through public surfaces.
- Added the local demo command, release documentation, and explicit MVP limitation record.

### 2026-07-25 - RB-101 PR opened and merge protection enabled
- Opened [PR #13](https://github.com/vince-e10/route-buddy/pull/13) with the locally verified
  foundation.
- Proved `CI / required` fails for a deliberately broken health test and passes after restoration.
- Updated the strict `main` ruleset to require pull requests, current branches, resolved
  conversations, and the GitHub Actions check while continuing to block deletion and force pushes.

### 2026-07-25 - RB-101 foundation locally verified
- Built the Compose stack, Terraform data module, API and mock service skeletons, frozen shared
  models and seams, structured log redaction, and initial CI workflow.
- Verified 12 API tests, all four non-root workloads, the exact table set, memory-mode CI startup,
  persisted sentinel data across a Floci restart, and a Terraform re-apply with no changes.
- Next checkpoint is the pull request, red-to-green CI proof, and required-check ruleset update.

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
