# outreach-build — STATE (read + written every run)

This file is the loop's memory. The cold-started loop reads it to know where it
is and writes it after every iteration. The counters here are the ONLY brake the
budget can rely on — nothing held in session memory survives a cold start.

started-at:        2026-06-28 (interactive build, user-driven; G0+G1 cleared by user: creds + schema decision)
last-run:          2026-06-28 — phase F GREEN (floor PASS + judge PASS); advancing to G
current-phase:     G
global-iterations: 6
G_SEND:            unset   (human-only; the loop must never set this)

## Per-phase progress
Legend: floor = `verify.sh` deterministic PASS · judge = separate evaluator-agent
PASS. A phase is GREEN only when floor = PASS AND judge = PASS. `rounds` = fix-
rounds spent (budget: max 2, then leave + report).

| Phase | Name | floor | judge | rounds | green? |
|---|---|---|---|---|---|
| A | Foundations | PASS | PASS | 1 | YES |
| B | find_leads | PASS | PASS | 0 | YES |
| C | Compliance firewall (PECR) | PASS | PASS | 0 | YES |
| D | enrich_company | PASS | PASS | 0 | YES |
| E | draft_email (mechanism only) | PASS | PASS | 0 | YES |
| F | Approval queue | PASS | PASS | 0 | YES |
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
- Phase A GREEN+committed (966bbe1). Phase B GREEN: 50 active SIC-68310 leads in
  outreach.leads (deduped), audit row each. CH client = Basic auth + per-run cap
  + 0.6s interval.
- Phase C GREEN: firewall classifies whole backlog (subscriber_class is null);
  50 leads all corporate (ltd estate agents), 0 suppressed; suppress-path covered
  by seeded rolled-back test. check_suppression(suppressions ∪ public.leads),
  _safe_ident guards the table name. Judge: rigorous PASS, no fall-through.
- Phase D GREEN: provider-agnostic WebsiteResolver (inline default; firecrawl +
  brave swappable by WEBSITE_RESOLVER env + key + cap). Runtime provider decided =
  FIRECRAWL (free 1,000 credits/mo, NO card; Brave needs a card; scraping stays
  free httpx). Live: Burnap+Abel + Naish verified via MillionVerifier (real 'ok');
  Kays + 2 no-site + Manor(mismatch) discarded. Inline-discovery mismatch on
  SC578527 caught + corrected (discarded + audited).
- Phase E GREEN: draft mechanism (load placeholder playbook → inline provisional
  responder → check_envelope) wrote 2 provisional drafts to body_original (status
  awaiting_approval), 76/75 words, compliant. Judge: no conversion copy invented.
- Phase F GREEN: review.py (CLI list/approve/reject; --by required; body_original
  immutable; approve re-checks envelope on body_final; state-machine-guarded;
  audit per decision). 2 drafts approved (Burnap as-is; Naish edited → body_final
  diff captured). states.py: DRAFTED→{approved,rejected,discarded}.
- PHASE G (send — HARD-GATED) carry-forward: send_email sends body_final via MS
  Graph from a SEPARATE warmed domain (GRAPH_SENDER, never @settlepay.uk). Guards
  BEFORE any send (dry-run included): global kill switch, individual/unknown block,
  check_suppression(suppressions ∪ enquiries), per-inbox daily cap (3–5). LIVE send
  REFUSES unless config.send_enabled() (G_SEND truthy) — the loop NEVER sets G_SEND.
  Build = dry-run/test mailbox only; 0 live sends. Needs migration 0002 (sends.from_inbox).
