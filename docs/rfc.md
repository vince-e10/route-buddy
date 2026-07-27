# Route Buddy - Live RFC

_Repos touched:_ [vince-e10/route-buddy](https://github.com/vince-e10/route-buddy)
_Issues:_ [RB-100 #10](https://github.com/vince-e10/route-buddy/issues/10), plus
[RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2) through
[RB-107 #8](https://github.com/vince-e10/route-buddy/issues/8), and post-MVP reliability work
[RB-108 #20](https://github.com/vince-e10/route-buddy/issues/20) through
[RB-112 #24](https://github.com/vince-e10/route-buddy/issues/24)
_Docs:_ all project docs live in this `docs/` folder alongside the code (owner decision
2026-07-25, overriding the docs-in-vault convention): `high-level-requirements.md` (spec),
`design.md` (approved RFC), `contracts.md` (normative interfaces), `execution-plan.md` (delivery),
this file (live status).

## Current State
_Last updated: 2026-07-27_

**Goal:** AI agent that books and manages ride-hailing trips end to end (SG market, mocked Uber Guest Rides provider, FastAPI, DynamoDB on an AWS-compatible local emulator, Terraform IaC), with structurally enforced confirmation gate, append-only action log, and grounded answers.
**Status:** MVP implemented. RB-111 defines the future AWS trust bootstrap. RB-112 defines the
complete single-task AWS demo runtime and validates it offline. The project has no AWS account;
no bootstrap, live plan, or apply is required.
**Next step:** Review [RB-112 PR #39](https://github.com/vince-e10/route-buddy/pull/39).
Continue using Compose and mocked-provider Terraform tests as the deployment simulation.
**Open questions:**
- OneMap token refresh flow (token registered, ~3-day expiry) - implementor task, not a blocker
- Action-log retention policy - production decision
- Uber partner approval timeline - business, needed only for real-provider swap
- Whether the project will ever open an AWS account and perform the deferred live-AWS path.

## Log

### 2026-07-27 - RB-112 PR opened
- Opened [PR #39](https://github.com/vince-e10/route-buddy/pull/39) with the offline-validated AWS
  demo runtime, sanitized issue evidence, and explicit simulation-only deviations.

### 2026-07-27 - RB-112 AWS demo simulated locally
- Added the complete AWS demo runtime under `infra/aws`: private single-task Fargate service,
  CIDR-restricted HTTPS ALB, two-AZ VPC with one NAT, DynamoDB gateway endpoint, reused hardened
  data module, Secrets Manager metadata, exact IAM policies, and bounded logs.
- Added mocked-provider Terraform tests for network exposure, one-task topology, image and CIDR
  validation, secret injection, table names, IAM resource scope, optional IPv6, and access logs.
- Confirmed the project is simulation-only. No AWS account exists, no live plan or apply was run,
  and the deployment note in [PR #38](https://github.com/vince-e10/route-buddy/pull/38) is
  deferred.
- Recorded the ECS ceiling: one task has one shared task role, so separate API and mock-Uber IAM
  identities require separate tasks.

### 2026-07-27 - RB-111 PR opened
- Opened [PR #38](https://github.com/vince-e10/route-buddy/pull/38) with the locally verified AWS
  trust bootstrap and documented post-merge live-AWS acceptance path.

### 2026-07-27 - RB-111 AWS bootstrap implemented locally
- Added a single Terraform bootstrap root with private versioned S3 state, native lock files,
  exact GitHub OIDC trust, separate roles, a runtime-role permissions boundary, and two immutable
  ECR repositories.
- Added an offline native Terraform security test and a manual main-only bootstrap workflow with
  exact action SHAs, a protected Environment, one saved plan, and no destroy path.
- Terraform format, initialization, validation, both native security tests, and workflow lint
  passed. Two cold release-gate runs each passed 212 API/evaluator tests and 21 mock-provider
  tests on Terraform 1.15.8.
- Implementation review found and fixed the first-bootstrap backend circularity by using a real
  temporary local backend for the one-time apply before migrating that state to S3.
- Selected the documented one-time local administrator apply and state-migration path because no
  pre-existing organization bootstrap role was supplied for this repository.
- Upgraded the local Terraform image and required version to 1.15.8 while retaining AWS provider
  6.56.0. Documentation consulted on 2026-07-27: current GitHub OIDC and Environment guidance,
  AWS GitHub OIDC trust and ECR guidance, and HashiCorp S3 backend guidance.

### 2026-07-27 - RB-110 deterministic write selection implemented locally
- Opened [RB-110 PR #37](https://github.com/vince-e10/route-buddy/pull/37).
- Required CI passed both cold release-gate runs.
- Recorded the [RB-108 baseline evidence](https://github.com/vince-e10/route-buddy/issues/20#issuecomment-5082397293)
  and the unchanged post-hardening evaluation in
  [RB-109 PR #36](https://github.com/vince-e10/route-buddy/pull/36): valid wrong write proposals
  recurred across three evaluator runs and activated RB-110.
- Removed booking and cancellation from production, fake, and live-evaluator model schemas and
  dispatch. The model now has exactly four read-only tools; legacy write calls are rejected.
- Added exact quote/trip card selection over the frozen `action_request` WebSocket shape. The
  server validates current session state, creates a frozen pending action, and records
  `requested/user` then `verified/system`.
- Preserved selection, confirmation, and execution as separate steps. Provider writes remain
  exclusive to `confirm.py`.
- Implementation re-review found no remaining Critical or Important issues. Two cold
  `scripts/e2e.sh` runs each passed 212 API/evaluator tests and 21 mock-provider tests; the
  optional Node browser-state test passed separately on the host.

### 2026-07-26 - RB-109 unchanged post-hardening evaluation completed
- The same fixture SHA, configured models, three runs, temperature, and token cap completed all
  204 case-runs with no transport failure.
- GLM-4.5-Air passed 81/102 case-runs; MiniMax M2 passed 83/102; overall was 164/204.
  Structural validity remained 100%. Across all attempts, the remaining non-pass outcomes were
  26 `should_clarify` and 22 `unnecessary_refusal`; 40 case-runs ended without a pass.
- Deterministic write selection is activated for RB-110 #22. GLM proposed structurally valid
  evaluator `cancel_ride` calls for `cancel-completed-trip` in runs 1, 2, and 3. MiniMax proposed
  structurally valid evaluator `book_ride` calls for `book-expired-quote` in runs 1, 2, and 3,
  plus a completed-trip cancellation in run 3. The unchanged `book-expired-quote` fixture
  supplies no fare enum, so those booking proposals were JSON/Pydantic-valid, not
  allowlist-validated. In production, dynamic schemas omit `book_ride` when all quotes are
  expired and omit `cancel_ride` for non-cancellable trips; handlers still recheck expiry,
  ownership, and status. RB-109 does not implement the RB-110 follow-up.
- Report secret and PII pattern scan: clean.
- Compatibility verification found that
  `parallel_tool_calls: false` plus strict `provider.require_parameters` returned HTTP 404 for
  both configured routes. Removing only `require_parameters` restored inference while
  `data_collection: deny`, exact schemas, server validation, multiple-call rejection, and the
  confirmation gate remained.

### 2026-07-26 - RB-109 tool-proposal hardening implemented
- Model tool calls are untrusted proposals. Route Buddy validates every proposal; invalid
  proposals are rejected and logged. Booking or cancellation is possible only after the user
  confirms the exact server-frozen action.
- Generated Draft 7-compatible schemas match Pydantic validation, reject extra properties, and
  expose only tools and IDs legal for one current trip snapshot.
- Every request is sequential. One structural rejection may receive one correction pinned to the
  fallback model; the fallback passes through the same validation and cannot trigger another
  correction.
- Invalid proposals record `requested` then `verified` audit entries, with raw argument text
  capped at 512 characters.
- OpenRouter's `models` fallback applies to request errors. Current Auto Exacto provider ordering
  uses supplied tool schemas as a quality signal. Response Healing applies to non-streaming
  `response_format` JSON content when enabled, not ordinary tool arguments.

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
