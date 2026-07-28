# Route Buddy - Project Retrospective and Production Readiness

_As of: 2026-07-28_
_Scope: repository history, live RFC, design and contracts, GitHub issues and pull requests, and
recorded verification evidence_

## Executive assessment

Route Buddy was planned and delivered with strong systems thinking: constraints first, safety
enforced in code, uncertain dependencies validated before adoption, and decisions changed when
evidence contradicted the original approach.

The result is a complete local/mock MVP and a well-defined AWS demo deployment contract. It is
not a production ride-booking service. No live AWS deployment or real Uber integration has been
validated, and the multi-user and multi-replica production work remains open.

The engineering process was mature and evidence-driven. The main imbalance was sequencing:
technical feasibility and production architecture were validated more deeply than user demand,
provider access, and operational use.

## What was planned

The original requirements were deliberately small:

- Discover and compare Singapore ride options.
- Book, track, and cancel rides through a multi-turn conversation.
- Require explicit confirmation for every real-world action.
- Record every action attempt in an append-only audit log.
- Ground every answer in tool output and provided context.
- Use FastAPI and bring the containerized system up with one command.
- Keep the local AWS-shaped stack portable to real AWS.

The plan then evolved through explicit phases:

| Phase | Purpose | Outcome |
| --- | --- | --- |
| Product definition | Fix the user flow and three invariants | [High-level requirements](high-level-requirements.md) |
| Feasibility research | Test Uber access, local AWS, LLM, and geocoding assumptions | [Approved design](design.md) |
| Contract freeze | Make parallel implementation safe | [Frozen contracts](contracts.md) |
| MVP delivery | Implement RB-100 through RB-107 in dependency waves | Local/mock MVP complete |
| AI reliability | Measure and reduce model-selection risk in RB-108 through RB-110 | Model writes removed |
| AWS demo | Add RB-111 through RB-113 bootstrap, runtime, and deployment controls | Offline-validated contract |
| Production roadmap | Define RB-114 through RB-122 | Open and deferred |

## How the approach was selected

The recurring decision process was:

1. Identify the non-negotiable constraint.
2. Research whether the assumed solution was actually available.
3. Compare explicit alternatives and their tradeoffs.
4. Add a measurable gate before committing.
5. Preserve a bounded fallback.
6. Revise the design when evidence changes.

Important decisions followed this pattern:

- Uber Guest Rides was partner-gated with no self-serve sandbox, so the MVP used a
  contract-faithful deterministic mock instead of blocking on external approval.
- LocalStack added account-token, persistence, and licensing friction, so Floci 1.5.33 was
  selected only after RB-100 proved the required DynamoDB and Terraform behavior.
- OpenRouter models were selected for low-cost tool calling, but all model output was treated as
  untrusted.
- Live evaluation showed valid-but-wrong write proposals. RB-110 responded by removing booking
  and cancellation from the model surface and requiring the user to select exact structured
  cards before confirmation.
- SQS, scheduled rides, additional providers, authentication, and high availability were kept
  out of the MVP until a real requirement justified them.

The strongest decision was moving write-target selection out of the model. It converted a
probabilistic safety risk into deterministic user and server behavior.

## What was delivered

The completed system includes:

- A one-command Docker Compose stack.
- A deterministic mock of the Uber Guest Rides lifecycle and webhooks.
- DynamoDB repositories for sessions, trips, pending actions, and the append-only action log.
- Uber provider, OneMap geocoder, and OpenRouter-compatible LLM adapters.
- A stateful agent loop exposing four read-only tools.
- Exact structured booking and cancellation selection.
- Scoped, expiring, single-use confirmation tokens.
- Provider writes isolated to the confirmation endpoint.
- A WebSocket chat UI with live trip updates.
- Secret and PII redaction, security headers, and non-root containers.
- A 34-case live-model golden-set evaluator.
- Local, bootstrap, and simulated AWS Terraform roots.
- A protected, OIDC-based AWS demo deployment workflow using immutable images and a saved plan.

Recorded project evidence before this closure included:

- 17 merged pull requests between 2026-07-25 and 2026-07-27.
- 14 of 23 delivery and production-readiness issues closed.
- Two cold release-gate passes in required CI.
- 213 API/evaluator tests with one optional browser test skipped, plus 21 mock-provider tests, in
  the final recorded gate.
- A successful required CI run on the final RB-113 `main` commit.

## What remains

The production dependency chain remains represented by open GitHub issues:

| Issue | Remaining capability |
| --- | --- |
| [RB-114 #26](https://github.com/vince-e10/route-buddy/issues/26) | Authentication and cross-user isolation |
| [RB-115 #27](https://github.com/vince-e10/route-buddy/issues/27) | Per-user rider profiles and PII isolation |
| [RB-116 #28](https://github.com/vince-e10/route-buddy/issues/28) | Cross-replica WebSocket delivery |
| [RB-117 #29](https://github.com/vince-e10/route-buddy/issues/29) | Distributed session coordination |
| [RB-118 #30](https://github.com/vince-e10/route-buddy/issues/30) | Global per-user rate limits |
| [RB-119 #31](https://github.com/vince-e10/route-buddy/issues/31) | Approved Uber OAuth and signed webhooks |
| [RB-120 #32](https://github.com/vince-e10/route-buddy/issues/32) | Persistent multi-replica mock state |
| [RB-121 #33](https://github.com/vince-e10/route-buddy/issues/33) | Horizontal correctness and capacity evidence |
| [RB-122 #34](https://github.com/vince-e10/route-buddy/issues/34) | Production HA, autoscaling, alarms, and rollback |

Production also requires decisions or evidence that are not satisfied by code alone:

- Uber for Business approval and commercial permission for the intended service.
- A live AWS deployment, owner smoke test, and operational soak.
- User testing of the conversational and confirmation experience.
- Independent security and implementation review.
- Action-log retention, privacy, incident ownership, and service-level objectives.

## Production readiness

These are judgment ranges, not schedule commitments:

| Destination | Readiness | Assessment |
| --- | ---: | --- |
| Local portfolio or demonstration MVP | 100% | Complete and verified |
| Protected AWS demo using mock Uber | 85-90% | Implementation exists; live deployment evidence is missing |
| Single-owner real-Uber pilot | 45-55% | Externally blocked and missing live provider validation |
| Public multi-user production | 35-45% | Identity, distributed correctness, capacity, HA, and operations remain |

Issue count alone overstates readiness because the remaining work contains the external critical
path and most operational risk.

## Process assessment

What worked well:

- Safety invariants were structural, not prompt instructions.
- High-risk assumptions were converted into explicit gates.
- Non-goals prevented obvious provider and queue overbuilding.
- Frozen interfaces supported parallel delivery without uncontrolled contract drift.
- Live evidence changed the architecture instead of being explained away.
- Verification covered public behavior, failure paths, security properties, and cold startup.

What could improve:

- Validate user value and workflow preference as deliberately as technical feasibility.
- Start externally gated provider approval earlier because it controls the real launch path.
- Allow more soak time between large changes.
- Require independent review before treating self-reviewed, AI-assisted work as production-ready.
- Avoid building additional production infrastructure until the project has a real account,
  provider access, and an explicit launch decision.

## Closure

The Route Buddy MVP exercise is concluded as of 2026-07-28.

Accepted outcome:

- The local/mock MVP is complete.
- The three safety invariants are implemented and tested.
- The production architecture and remaining dependency chain are documented.
- The repository does not claim live AWS, real Uber, multi-user, or public production readiness.

No further work is scheduled. RB-114 through RB-122 remain open as a deferred production roadmap,
not unfinished MVP scope. Resume only after an explicit owner decision backed by a real launch
goal, Uber approval progress, and willingness to operate a live AWS environment.
