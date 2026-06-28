# outreach — SettlePay cold-email pipeline (mechanism only)

UK PECR-compliant agentic cold-email outreach for SettlePay. Built phase by phase
by the `outreach-build` loop (see `../loops/outreach-build/`). This project builds
the drafting **mechanism only** — the conversion strategy (copy, timing, cadence)
is deferred and arrives as a separate drafting playbook.

Writes to its **own `outreach` schema** in the SettlePay Supabase Postgres
(project `xqpbcoldcqfxfwhcqlcy`). It NEVER touches the website's `public` tables;
it only *reads* the inbound enquiry source (`public.<ENQUIRY_SOURCE_TABLE>`) to
suppress existing enquirers.

## Setup

```bash
cp .env.example .env          # then fill in secrets (gitignored)
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "psycopg[binary]" httpx python-dotenv pytest
.venv/bin/python -m outreach.migrate      # apply migrations/*.sql (idempotent)
```

## Verify (the deterministic FLOOR)

```bash
../loops/outreach-build/verify.sh         # current phase from STATE.md
../loops/outreach-build/verify.sh A       # force a phase
.venv/bin/python -m pytest -q             # unit tests
```

## Layout

```
migrations/         SQL migrations (0001_init.sql = schema + enums + tables)
prompts/            drafting playbook placeholder (phase E)
outreach/           the package
  config.py         .env-driven settings (DB, schema, caps, provider, G_SEND gate)
  db.py             psycopg connection; search_path -> outreach, public
  states.py         LeadState / SubscriberClass + transition rules (suppress = fail-safe)
  audit.py          audit_log writer (lawful_basis='legitimate interests')
  llm.py            LLMProvider: inline (default, Claude Max) + api (later)
  migrate.py        apply migrations
tests/              floor_a..floor_h marked unit tests
```

## Safety invariants (see ../loops/outreach-build/CONTEXT.md)

- No live send without human gate **G-SEND**; `G_SEND` unset ⇒ dry-run only.
- Individual/unknown subscribers are never in a contactable state.
- `body_original` is immutable; human edits go to `body_final`.
- Secrets only in `.env` (gitignored); UK identity, never claims SettlePay's own
  FCA authorisation.
