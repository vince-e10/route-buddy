# Route Buddy - Execution Plan

_Date:_ 2026-07-25 · _Design:_ `docs/design.md` (approved) · _Contracts:_ `docs/CONTRACTS.md`
(normative) · _Tickets:_ `docs/tasks/RB-101..RB-107`

## How this plan works

Seven tickets, four waves. Tickets inside a wave are independent: they touch disjoint files (the
ownership map in CONTRACTS section 13 is binding) and integrate only through interfaces frozen in
`docs/CONTRACTS.md`. Cross-component behavior is deliberately untested until RB-107, which pairs
everything live and is the release gate. One agent per ticket; an agent needs ONLY its ticket
file + the two docs it names.

```
Wave 1          Wave 2 (parallel)         Wave 3 (parallel)        Wave 4
┌────────┐      ┌──────────────────┐      ┌────────────────┐      ┌──────────────┐
│ RB-101 │──┬──▶│ RB-102 mock-uber │──┬──▶│ RB-105 agent   │──┬──▶│ RB-107       │
│ founda-│  │   ├──────────────────┤  │   │ core + gate    │  │   │ integration, │
│ tion   │  ├──▶│ RB-103 storage   │──┤   ├────────────────┤  ├──▶│ e2e, README  │
└────────┘  │   ├──────────────────┤  │   │ RB-106 WS + UI │──┘   └──────────────┘
            └──▶│ RB-104 adapters  │──┘   └────────────────┘
                └──────────────────┘
RB-105 needs RB-103 + RB-104 done. RB-106 needs RB-103 done (RB-102 only gates RB-107).
RB-105 and RB-106 meet ONLY through `app.registry` (a wave-1 artifact): RB-105 registers the
agent service, RB-106 registers the publisher; neither imports the other's files. Their live
pairing is proven in RB-107.
```

| Ticket | Title | Wave | Size | Hard dependencies |
|---|---|---|---|---|
| RB-101 | Compose stack, Terraform IaC, skeletons, shared models, redaction | 1 | M | - |
| RB-102 | mock-uber: Guest Rides mock + lifecycle simulator + webhooks | 2 | L | RB-101 |
| RB-103 | DynamoDB repositories (sessions, trips, action log, pending actions) | 2 | M | RB-101 |
| RB-104 | UberAdapter + OneMapGeocoder + StubGeocoder | 2 | M | RB-101 |
| RB-105 | LLM client, agent loop, tools, confirmation gate, confirm + webhook endpoints | 3 | L | RB-103, RB-104 |
| RB-106 | WebSocket transport + chat UI | 3 | M | RB-103 |
| RB-107 | Live integration, e2e suite, security verification, README | 4 | M | all |

## Delegation protocol (per ticket)

Dispatch brief for the implementing agent - paste this, filling the ticket id:

> Implement ticket `docs/tasks/RB-1xx-*.md` in `~/Documents/Obsidian Vault/route-buddy`.
> Read, in order: your ticket file, `docs/CONTRACTS.md`, the `docs/design.md` sections your
> ticket lists, `AGENTS.md`. Rules: (1) `docs/CONTRACTS.md` is frozen - if it conflicts with
> anything or looks wrong, STOP and report instead of improvising; (2) create/modify ONLY the
> files your ticket owns (CONTRACTS section 13); (3) this folder is NOT a git repo - no git
> commands, no commits; (4) secrets only via `.env` (never ask for or echo values); (5) never
> call real Uber or live OneMap from tests; (6) work through the ticket's test plan - acceptance
> checkboxes are your definition of done; (7) finish by ticking the checkboxes you satisfied and
> appending a close-out note at the bottom of the ticket file (what you built, deviations, exact
> verify commands you ran). If a checkbox cannot be ticked, say so explicitly - do not claim done.

Verification between waves (the orchestrator, not the implementing agents):
- After wave 1: run RB-101's manual verification block yourself (compose up, tables, healthz,
  restart cycle). Do not start wave 2 on a red skeleton.
- After each wave-2/3 ticket: run the ticket's own test command from its close-out; spot-read the
  diff for ownership-map violations and contract drift (field renames are the classic failure).
- Wave 4 (RB-107) is the real gate: its agent fixes integration bugs and must list every
  cross-ticket fix in its close-out.

Recommended agent setup per your delegation model: implementation model of your choice per
session default; each wave-2/3 ticket is a self-contained brief, so agents can run concurrently
in this folder because their file sets are disjoint - but do NOT run two agents that share a
requirements.txt edit (only RB-107 may add a dependency, and only the e2e client).

## What is deliberately NOT in the tickets

- Prod Terraform modules (ECS/ALB/IAM/Secrets Manager) - design.md section 12/prod path; built at
  productionization, not MVP
- Lyft/Grab, scheduled rides, multi-user auth, SQS - explicit non-goals (design.md section 2)
- OneMap token refresh beyond the in-process cache - the RB-104 design (lazy fetch + refresh on
  expiry/401) IS the refresh flow; nothing more is needed for MVP

## Risk register

| Risk | Mitigation |
|---|---|
| Parallel agents drift from contracts | Single normative CONTRACTS.md; verbatim fixture reuse (RB-104 tests use RB-102's exact response spec); RB-107 enforcement pass |
| Cheap LLM misbehaves at runtime | Structurally irrelevant to safety (gate is code); quality fallback chain is config: primary -> fallback model -> flip write turns to Claude (design.md 3.3) |
| LocalStack free-tier surprises (auth token, no persistence) | Ephemeral-state design baked into RB-101 (clean apply per start); e2e runs twice from cold to prove it |
| Uber contract fidelity wrong somewhere | Mock mirrors documented field names verbatim; deviations surface at the adapter, both sides trace to CONTRACTS section 9 |
| Agents "fix" invariants away (e.g. add a confirm bypass for tests) | RB-105's structural test (`test_llm_cannot_execute`) + AGENTS.md invariants; orchestrator diff review between waves |

## Sequence for the owner

1. Dispatch RB-101. Verify wave 1 yourself (10 minutes).
2. Dispatch RB-102, RB-103, RB-104 concurrently.
3. Dispatch RB-105 and RB-106 concurrently.
4. Dispatch RB-107. Review its close-out (integration fixes + security checklist) - that review
   is the MVP acceptance.
5. Demo: `scripts/demo.sh`, browser at `http://localhost:8000`.
