# outreach-build — STATE (read + written every run)

This file is the loop's memory. The cold-started loop reads it to know where it
is and writes it after every iteration. The counters here are the ONLY brake the
budget can rely on — nothing held in session memory survives a cold start.

started-at:        2026-06-28 (interactive build, user-driven; G0+G1 cleared by user: creds + schema decision)
last-run:          2026-06-28 — phase A GREEN (floor PASS + judge PASS); advancing to B
current-phase:     B
global-iterations: 1
G_SEND:            unset   (human-only; the loop must never set this)

## Per-phase progress
Legend: floor = `verify.sh` deterministic PASS · judge = separate evaluator-agent
PASS. A phase is GREEN only when floor = PASS AND judge = PASS. `rounds` = fix-
rounds spent (budget: max 2, then leave + report).

| Phase | Name | floor | judge | rounds | green? |
|---|---|---|---|---|---|
| A | Foundations | PASS | PASS | 1 | YES |
| B | find_leads | – | – | 0 | no |
| C | Compliance firewall (PECR) | – | – | 0 | no |
| D | enrich_company | – | – | 0 | no |
| E | draft_email (mechanism only) | – | – | 0 | no |
| F | Approval queue | – | – | 0 | no |
| G | send (hard-gated, dry-run) | – | – | 0 | no |
| H | Operational wiring | – | – | 0 | no |

## Spend this run (reset/accumulate per run; cross-check against HUMAN-GATES caps)
- Companies House requests: 0   (cap ≤50/run during build)
- MillionVerifier verifications: 0   (cap ≤20/run during build)
- LLM API calls: 0   (inline provider default — 0 paid calls expected during build)
- Live email sends: 0   (MUST stay 0 until G-SEND; dry-run only)

## Anomalies surfaced (G2 — out of remit, not fixed here)
- Live `public` schema had only `leads` (website inbound enquiries); no `enquiries`
  table. Edge Function repoint `leads → enquiries` is the user's uncommitted WIP.
  Resolved by decision: pipeline uses its OWN `outreach` schema; firewall suppresses
  against `public.<ENQUIRY_SOURCE_TABLE>` (leads now → enquiries later). Website
  repoint remains out of remit.

## Notes / handoff
- Connection: direct host is IPv6-only (no resolve); using session pooler
  aws-1-eu-north-1:5432. Python 3.12 via uv venv at outreach/.venv.
- Phase A: migration 0001 applied to live DB (outreach schema). Floor A PASS.
  Next: run independent judge for A; if PASS → mark green, advance to B (find_leads).
