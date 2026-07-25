# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Cursor, …) working in this repo.
`CLAUDE.md` is a pointer that imports this file. Keep this file the single source of truth -
do not fork guidance into a second doc.

## What this is

**Route Buddy** - an AI agent that books ride-hailing trips and manages them end to end:
discover options, compare prices, book, track, cancel. MVP provider: **Uber**. Later: Lyft, Grab.

All project documents live in `docs/` in this folder (deliberate exception to the
docs-live-in-the-vault convention - we work on them here):

- `docs/high-level-requirements.md` - the spec
- `docs/design.md` - approved RFC / detailed design (2026-07-25). Decisions recorded there are
  settled; read it before implementing, don't re-litigate.
- `docs/contracts.md` - frozen cross-component interfaces; implementation must match them.
- `docs/execution-plan.md` - dependency waves and links to implementation issues.
- `docs/rfc.md` - live status: goal, status, next step, open questions, dated log

This file is how to work in the repo.

## Git workflow

This folder is a Git repository. Work on feature branches, validate changes before committing,
push branches, and open PRs against `main`. Never commit or push directly to `main`; the owner
merges PRs.

Every implementation change starts from a [GitHub issue](https://github.com/vince-e10/route-buddy/issues).
GitHub Issues are the single source of truth for task scope, acceptance criteria, dependencies,
and status. Do not create local task files. Pull requests must link their issue with
`Closes #<issue>` and record verification results and approved deviations.

Treat every change as production work: preserve the three invariants, keep changes reviewable,
test behavior in proportion to risk, and leave `main` releasable.

## File naming

- Use lowercase kebab-case for project-owned Markdown documents and non-Python directories.
- Use snake_case for Python modules and package directories.
- Keep conventional tool-recognized names unchanged: `AGENTS.md`, `CLAUDE.md`, `README.md`,
  `LICENSE`, `Dockerfile`, and similar platform-required names.
- Before delivery, verify every new path follows this convention. Naming consistency is a
  required acceptance check, not optional cleanup.

## Status: IMPLEMENTATION STARTED (RB-101 foundation)

RB-101 provides the Compose and Terraform foundation (`docker-compose.yml`, `infra/`), API
skeleton and shared contracts (`api/app/`), service Dockerfiles, and the initial mock-Uber health
placeholder (`mock-uber/app/main.py`). API health, registry, and log-redaction tests live in
`api/tests/`. Compose startup, DynamoDB persistence across a Floci restart, and a no-change
Terraform re-apply have been verified.

Everything under "Intended shape" below remains a decision unless the paths above say otherwise.

## Intended shape

```
chat UI ──▶ FastAPI ──▶ agent loop ──▶ tools ──▶ provider adapter ──▶ Uber API
                │                        │
                │                   confirmation gate (write tools only)
                └────────────────▶ action log (append-only, every attempt)
```

- **Backend: FastAPI** (fixed by the requirements). Python.
- **Provider adapter**: one interface, Uber the only implementation for MVP. Do NOT build
  Lyft/Grab stubs or a plugin registry before a second provider is real - YAGNI.
- **Cloud**: Floci 1.5.33 is the validated local AWS emulator
  ([RB-100 evidence](https://github.com/vince-e10/route-buddy/issues/10#issuecomment-5078441200)).
  The application and Terraform module use standard AWS interfaces so production uses real AWS
  without a rewrite. Pick AWS-native primitives over bespoke ones.
- **One command up**: `docker compose up` must bring the whole system (API, UI, Floci, any
  datastore) to a working state. If a change breaks that, it is not done.
- **Locked by the approved design** (details + rationale in the design doc): Singapore market;
  mock Uber Guest Rides container (real API is partner-gated); LLM via OpenRouter
  (`z-ai/glm-4.5-air` primary, `minimax/minimax-m2` fallback) behind an OpenAI-compatible client;
  SG OneMap geocoding behind a `Geocoder` interface; DynamoDB on pinned Floci 1.5.33; standard
  Terraform for ALL infra (no wrapper or shell-script init); the LLM never sees guest PII; no
  scheduled rides in MVP.

## Three invariants that must not be violated

1. **Confirmation gate on every real-world action.** No booking, no cancellation, no payment is
   executed without an explicit user confirmation for *that* action. A confirmation is scoped:
   confirming one ride never authorizes the next one, and re-planning after a price change needs
   a fresh confirm. Read-only tools (search, price quote, status) need no gate. Never add a
   "skip confirmation" flag, an auto-confirm timeout, or an agent-inferred approval.

2. **Action log records every attempt.** For each attempt, append: what was *requested*, what
   was *verified*, what was *executed*, what *happened* (including failures, refusals, and
   aborted confirmations). Append-only - never edit or delete an entry to make a run look clean.
   The log is the audit trail; a silent action is a bug.

3. **Grounded answers only.** The agent answers from tool output and the provided context, never
   from plausible-sounding invention: no guessed prices, ETAs, ride IDs, or driver details. If
   the data isn't in the source, say so. Prefer refusing/asking to fabricating, and prefer no
   tool call to a wrong tool call.

## Working conventions

- **Requirements win over cleverness.** FastAPI, containerized-one-command, the validated local
  AWS emulator, and the three invariants above are non-negotiable; anything else is open for the
  simplest thing that works.
- **Secrets**: never in code, chat, or committed files. Local dev reads a gitignored `.env`
  (commit a `.env.example` with key names and empty values only).
- **Never call the real Uber API from tests** - stub the adapter. A test that books a real ride
  is a broken test.
- **Multi-turn state**: the conversation is stateful (follow-ups like "cancel that one" must
  resolve). Keep resolution explicit against the action log / a session record - don't rely on
  the LLM remembering an ID.
- API tests use pytest. Keep one focused runnable check beside new non-trivial logic; don't
  scaffold a suite ahead of need.

## Commands

The canonical stack entry point is:

```bash
docker compose up          # whole system, one command (the requirement)
```
