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

## Operations console (local)

A **localhost-only** unified operations console (single operator, no auth — do not
expose publicly; it holds a service-role DB connection). One sidebar over **inbound
enquiries** + **outbound outreach**, in the shared SettlePay design system. Routes:

- **`/`** — combined overview: inbound enquiries KPIs + outbound outreach KPIs.
- **`/enquiries`** — inbound website-enquiry CRM (filter by status); per-enquiry
  record `/enquiry/<id>` (status + private notes; reads/updates `public.<table>`).
- **`/outreach`** — outbound live funnel (discovered → PECR-cleared → website →
  email → verified → drafted → approved → sent), yield-by-vertical, verification
  breakdown, graduation thresholds, compliance/safety, audit activity feed.
- **`/outreach/queue`** — approval queue (the human gate). Reuses `outreach.review`
  (envelope re-checked, audited, `body_original` immutable). Approving only advances
  a draft to `approved`; sending stays gated behind **G-SEND**.
- **`/outreach/leads`** — CRM of every discovered company (filter by state / vertical),
  per-lead record at `/outreach/lead/<company_number>`.
- **`/settings`** — read-only runtime safety posture + pipeline + data-source config.

### Always-on (recommended)

`ops/install-console.sh` deploys a self-contained runtime under
`~/Library/Application Support/SettlePayOutreach` and registers a macOS LaunchAgent
(RunAtLoad + KeepAlive), so the console is always reachable at
**http://localhost:8787/** across logouts and reboots. (The deploy lives
outside `~/Documents` because macOS TCC blocks launchd agents from reading it.)
Re-run the script after code changes to redeploy; `ops/uninstall-console.sh
[--purge]` removes it.

```bash
uv pip install --python .venv/bin/python ".[web]"   # for ad-hoc runs
ops/install-console.sh                              # always-on local service
```

### Ad-hoc run

```bash
.venv/bin/uvicorn outreach.web:app --port 8787   # then open http://localhost:8787/
```

The CLI alternative for the same approvals:
`python -m outreach.review list | approve <id> --by "Name" [--edit "..."] | reject <id> --by "Name"`.

See [`docs/system-assessment.md`](docs/system-assessment.md) for an honest review of
where the pipeline wastes effort and what to improve next, and
[`docs/pre-send-blockers.md`](docs/pre-send-blockers.md) for the go-live checklist.

## Pre-live-send tooling (gated)

```bash
python -m outreach.inbound      # ingest replies/bounces/unsubscribes -> suppressions
python -m outreach.dns_auth     # verify SPF/DKIM/DMARC on the sending domain
```

Both are required before `G_SEND`: the first keeps opt-outs/bounces honoured (PECR +
reputation), the second confirms deliverability. Sending stays gated regardless.

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
