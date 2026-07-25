# Route Buddy - Execution Plan

_Date:_ 2026-07-25 · _Design:_ `docs/design.md` (approved) · _Contracts:_ `docs/contracts.md`
(normative) · _Tracker:_ [GitHub Issues](https://github.com/vince-e10/route-buddy/issues)

## How this plan works

Eight issues, five waves. RB-100 passed its architecture gate; its decision PR must merge before
implementation starts.
Issues inside an implementation wave are independent: they touch disjoint files (the
ownership map in `contracts.md` section 13 is binding) and integrate only through interfaces frozen in
`docs/contracts.md`. Cross-component behavior is deliberately untested until RB-107, which pairs
everything live and is the release gate. Each implementer starts from the linked issue body and
the two repository documents it names.

```
Wave 0       Wave 1          Wave 2 (parallel)         Wave 3 (parallel)       Wave 4
┌────────┐   ┌────────┐      ┌──────────────────┐      ┌────────────────┐      ┌──────────────┐
│ RB-100 │──▶│ RB-101 │──┬──▶│ RB-102 mock-uber │──┬──▶│ RB-105 agent   │──┬──▶│ RB-107       │
│ Floci  │   │ founda-│  │   ├──────────────────┤  │   │ core + gate    │  │   │ integration, │
│ gate   │   │ tion   │  ├──▶│ RB-103 storage   │──┤   ├────────────────┤  ├──▶│ e2e, README  │
└────────┘   └────────┘  │   ├──────────────────┤  │   │ RB-106 WS + UI │──┘   └──────────────┘
                         └──▶│ RB-104 adapters  │──┘   └────────────────┘
                             └──────────────────┘
RB-105 needs RB-103 + RB-104 done. RB-106 needs RB-103 done (RB-102 only gates RB-107).
RB-105 and RB-106 meet ONLY through `app.registry` (a wave-1 artifact): RB-105 registers the
agent service, RB-106 registers the publisher; neither imports the other's files. Their live
pairing is proven in RB-107.
```

| Issue | Title | Wave | Size | Hard dependencies |
|---|---|---|---|---|
| [RB-100 #10](https://github.com/vince-e10/route-buddy/issues/10) | Floci validated for exact Terraform and DynamoDB behavior | 0 | S | - |
| [RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2) | Compose stack, Terraform IaC, skeletons, shared models, redaction | 1 | M | [#10](https://github.com/vince-e10/route-buddy/issues/10) |
| [RB-102 #3](https://github.com/vince-e10/route-buddy/issues/3) | mock-uber: Guest Rides mock + lifecycle simulator + webhooks | 2 | L | [#2](https://github.com/vince-e10/route-buddy/issues/2) |
| [RB-103 #4](https://github.com/vince-e10/route-buddy/issues/4) | DynamoDB repositories (sessions, trips, action log, pending actions) | 2 | M | [#2](https://github.com/vince-e10/route-buddy/issues/2) |
| [RB-104 #5](https://github.com/vince-e10/route-buddy/issues/5) | UberAdapter + OneMapGeocoder + StubGeocoder | 2 | M | [#2](https://github.com/vince-e10/route-buddy/issues/2) |
| [RB-105 #6](https://github.com/vince-e10/route-buddy/issues/6) | LLM client, agent loop, tools, confirmation gate, confirm + webhook endpoints | 3 | L | [#4](https://github.com/vince-e10/route-buddy/issues/4), [#5](https://github.com/vince-e10/route-buddy/issues/5) |
| [RB-106 #7](https://github.com/vince-e10/route-buddy/issues/7) | WebSocket transport + chat UI | 3 | M | [#4](https://github.com/vince-e10/route-buddy/issues/4) |
| [RB-107 #8](https://github.com/vince-e10/route-buddy/issues/8) | Live integration, e2e suite, security verification, README | 4 | M | [#2](https://github.com/vince-e10/route-buddy/issues/2)-[#7](https://github.com/vince-e10/route-buddy/issues/7) |

## Delivery protocol (per issue)

1. Start from the issue body, then read `docs/contracts.md`, its named `docs/design.md` sections,
   and `AGENTS.md`.
2. Create a feature branch. Modify only the files owned by the issue in `contracts.md` section 13.
3. If the frozen contract conflicts with reality, stop and report it instead of improvising.
4. Keep secrets in `.env`; never ask for or echo values. Never call real Uber or live OneMap
   from tests.
5. Complete the issue's checks and acceptance criteria. Leave blocked items unchecked.
6. Open a pull request against `main` with `Closes #<issue>`. Record what was built, approved
   deviations, and exact verification commands and results in the pull request description.
7. Verify every new path follows the naming convention in `AGENTS.md`.

Verification between waves (the orchestrator, not the implementing agents):
- After wave 1: run RB-101's manual verification block (compose up, tables, healthz,
  restart cycle). Do not start wave 2 on a red skeleton.
- After each wave-2/3 issue: rerun the commands recorded in its pull request; spot-read the
  diff for ownership-map violations and contract drift (field renames are the classic failure).
- Wave 4 (RB-107) is the real gate: its agent fixes integration bugs and must list every
  cross-issue fix in its pull request description.

Recommended agent setup per your delegation model: implementation model of your choice per
session default; each wave-2/3 issue is a self-contained brief, so agents can run concurrently
in this folder because their file sets are disjoint - but do NOT run two agents that share a
requirements.txt edit (only RB-107 may add a dependency, and only the e2e client).

## What is deliberately NOT in the issues

- Prod Terraform modules (ECS/ALB/IAM/Secrets Manager) - design.md section 12/prod path; built at
  productionization, not MVP
- Lyft/Grab, scheduled rides, multi-user auth, SQS - explicit non-goals (design.md section 2)
- OneMap token refresh beyond the in-process cache - the RB-104 design (lazy fetch + refresh on
  expiry/401) IS the refresh flow; nothing more is needed for MVP

## Risk register

| Risk | Mitigation |
|---|---|
| Parallel agents drift from contracts | Single normative `contracts.md`; verbatim fixture reuse (RB-104 tests use RB-102's exact response spec); RB-107 enforcement pass |
| Cheap LLM misbehaves at runtime | Structurally irrelevant to safety (gate is code); quality fallback chain is config: primary -> fallback model -> flip write turns to Claude (design.md 3.3) |
| A future Floci version differs from required DynamoDB semantics | Keep `floci/floci:1.5.33` pinned; re-run the [RB-100 matrix](https://github.com/vince-e10/route-buddy/issues/10#issuecomment-5078441200) before upgrading; production validation still runs against AWS |
| Uber contract fidelity wrong somewhere | Mock mirrors documented field names verbatim; deviations surface at the adapter, both sides trace to `contracts.md` section 9 |
| Agents "fix" invariants away (e.g. add a confirm bypass for tests) | RB-105's structural test (`test_llm_cannot_execute`) + AGENTS.md invariants; orchestrator diff review between waves |

## Sequence for the owner

1. RB-100 passed its
   [Floci validation](https://github.com/vince-e10/route-buddy/issues/10#issuecomment-5078441200);
   merge its decision PR.
2. Implement [RB-101 #2](https://github.com/vince-e10/route-buddy/issues/2). Verify wave 1.
3. Implement [RB-102 #3](https://github.com/vince-e10/route-buddy/issues/3),
   [RB-103 #4](https://github.com/vince-e10/route-buddy/issues/4), and
   [RB-104 #5](https://github.com/vince-e10/route-buddy/issues/5) concurrently.
4. Implement [RB-105 #6](https://github.com/vince-e10/route-buddy/issues/6) and
   [RB-106 #7](https://github.com/vince-e10/route-buddy/issues/7) concurrently.
5. Implement [RB-107 #8](https://github.com/vince-e10/route-buddy/issues/8). Its integration
   fixes and security checklist are the MVP acceptance.
6. Demo: `scripts/demo.sh`, browser at `http://localhost:8000`.
