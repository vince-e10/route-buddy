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
- `docs/rfc.md` - live status: goal, status, next step, open questions, dated log

This file is how to work in the repo.

## Git workflow

This folder is a Git repository. Work on feature branches, validate changes before committing,
push branches, and open PRs against `main`. Never commit or push directly to `main`; the owner
merges PRs.

## Status: EMPTY SCAFFOLD

There is no application code yet - only requirements and this agent brief. Everything under
"Intended shape" below is a *decision*, not something you can read in the tree. When you build
a piece, replace its bullet here with what actually exists (paths, module names). Never describe
something as present when it isn't.

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
- **Cloud**: LocalStack locally, mapping 1:1 onto real AWS services so it productionizes without
  a rewrite. Pick AWS-native primitives over bespoke ones.
- **One command up**: `docker compose up` must bring the whole system (API, UI, LocalStack, any
  datastore) to a working state. If a change breaks that, it is not done.
- **Locked by the approved design** (details + rationale in the design doc): Singapore market;
  mock Uber Guest Rides container (real API is partner-gated); LLM via OpenRouter
  (`z-ai/glm-4.5-air` primary, `minimax/minimax-m2` fallback) behind an OpenAI-compatible client;
  SG OneMap geocoding behind a `Geocoder` interface; DynamoDB on LocalStack; Terraform + tflocal
  for ALL infra (no shell-script init); the LLM never sees guest PII; no scheduled rides in MVP.

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

- **Requirements win over cleverness.** FastAPI, containerized-one-command, LocalStack, and the
  three invariants above are non-negotiable; anything else is open for the simplest thing that
  works.
- **Secrets**: never in code, chat, or committed files. Local dev reads a gitignored `.env`
  (commit a `.env.example` with key names and empty values only).
- **Never call the real Uber API from tests** - stub the adapter. A test that books a real ride
  is a broken test.
- **Multi-turn state**: the conversation is stateful (follow-ups like "cancel that one" must
  resolve). Keep resolution explicit against the action log / a session record - don't rely on
  the LLM remembering an ID.
- No test framework is set up yet. When you add the first non-trivial logic, leave one runnable
  check next to it; don't scaffold a suite ahead of need.

## Commands

Nothing to run yet. As soon as the container stack exists, the canonical entry points go here:

```bash
docker compose up          # whole system, one command (the requirement)
```

Add real commands to this block when they exist - not placeholders.
