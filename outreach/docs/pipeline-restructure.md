# Outreach pipeline — restructure plan (agentic-pipeline IMPROVE audit)

_Audit date: 2026-07-19. Models verified against ~/.claude/LLM_MODELS.md +
live web (Gemini pricing, 2026-07). Bind nothing from memory._

## 1. Purpose (what the pipeline is for)
Turn UK company records into **compliant, personalised cold emails to real ICP
businesses** — small firms that take cash/bank-transfer and have **no** card
checkout — then send them under strict PECR + warm-up discipline. Correct output
= a lead that is corporate, ICP-fit, contactable (verified role email), and an
email that passes `check_envelope` and reads as true to that business.
Highest-stakes controls: `G_SEND` (human-only), the suppression list, the £50
spend cap. Volume envelope: 5→50 sends/day during warm-up.

## 2. LLM touchpoints today (all via one wrapper — good)
| Role | Where | Model now | Class it needs |
|---|---|---|---|
| Enrichment signal | `enrich.llm_signal` | claude-sonnet-4-6 | fast extraction (structured) |
| Draft email | `draft.draft_one` | claude-sonnet-4-6 | workhorse generation |
| Follow-up | `followup` | claude-sonnet-4-6 | workhorse generation |
| Reply classify | `inbound.classify` | none (regex) | keep deterministic |

`claude-sonnet-4-6` = $3/$15 per 1M. It's an expensive workhorse doing work a
cheap Gemini Flash does as well — and it ignores the $300 GCP credit entirely.

## 3. Findings (ranked by impact ÷ risk)

**F1 — Cost: wrong model class + ignores the GCP credit.** All LLM roles on
sonnet-4-6. `gemini-3-flash-preview` ($0.50/$3) is 5–6× cheaper on I/O and 10×
on output; `gemini-3.1-flash-lite` ($0.25/$1.50) cheaper still — **and both bill
against the $300 Vertex credit**. Classification: *assumed* (no bench; it was
just the verified api-provider default). → move signal to Flash-Lite, **bench**
drafting on Flash vs sonnet-4-6.

**F2 — Quality: ICP targeting is broken; no fit gate.** Discovery matches broad
SIC codes → it pulled consultancies and an investment bank. No size filter, no
"already takes card?" check. The email premise ("firms like yours still take
cash") is then false to the reader. → **fold an ICP-fit gate into enrichment**:
restructure `llm_signal` to return structured
`{icp_fit, already_takes_card, size_band, signal, confidence}` from the page
text we already scrape (one call, no extra cost), and **discard non-fit leads
before drafting**. Add Companies House size filters (accounts category
micro/small; incorporation age) at discovery. Fail-closed: unsure → not fit →
not admitted.

**F3 — Amortisation: it's a push-conveyor, not a reservoir.** Every tick pushes
fixed DISCOVER/ENRICH/DRAFT batches regardless of backlog; drafting drains
`enriched` to zero (why the pool was empty). → **demand-pull reservoir**: hold
`READY_POOL_TARGET` enriched-and-fit leads; discover/enrich run **only to refill
to target**; draft/send drain at the warm-up cap. This is the "durable enriched
lead list" — the SQL table `outreach.leads`+`enrichment` IS the list; add a
**CSV export** for inspection/portability. Enrichment spend then happens once per
lead, in efficient batches, and idles when the pool is full.

**F4 — No structured output (doctrine 5).** Signal + draft are free text. → JSON
schema on the enrichment/ICP call and any classifier (Gemini JSON mode). Draft
stays prose but is gated by the deterministic `check_envelope` (family-
independent — good).

**F5 — No bench harness (doctrine 10).** Nothing proves a model/prompt change. →
build a small bench: ~15 frozen leads with cached page text; score drafts on
envelope-pass, word count, and an ICP-premise rubric; compare models head-to-
head. **Prerequisite to any model swap.**

**F6 — Telemetry: cost fn is Anthropic-only; playbook re-sent uncached.**
`spend.anthropic_cost_gbp` is hardcoded; the ~1,500-token playbook is re-billed
every draft. → generalise to `cost_gbp(provider, model, in, out)` (Gemini thinking
billed at output rate); use **batch mode (−50%)** for the non-interactive
enrichment/draft runs and **prefix caching** for the playbook.

**F7 — Verification decorrelation (doctrine 3/4).** Compliance rests on the
deterministic envelope (good). With the F2 ICP gate protecting the premise
upstream, a semantic verifier is optional at this scale; if added, it must be a
**different family** than the drafter (draft on Gemini → verify on Claude Haiku).
Note, don't over-build now.

## 4. Target architecture
```
FILL THE RESERVOIR (batchy, cheap, amortised — runs only when pool < target)
  discover ──▶ classify(PECR) ──▶ resolve+scrape ──▶ verify email
                                          │
                                          ▼
                         enrich+ICP-fit call  (Gemini Flash-Lite, JSON)
                         {icp_fit, already_takes_card, size, signal}
                                          │  discard non-fit / already-card
                                          ▼
                              READY POOL  (outreach.leads state=enriched)
                              └─ CSV/SQL export, freshness-stamped
DRAIN THE RESERVOIR (paced by warm-up cap)
  draft (Gemini Flash, cached playbook) ──▶ envelope gate ──▶ review ──▶ send
```

## 5. Model bindings (proposed — verify live at bind time)
| Role | Model | Effort | Rationale |
|---|---|---|---|
| ICP-fit + signal | `gemini-3.1-flash-lite` | thinking off | mechanical structured extraction, highest volume, cheapest |
| Draft / follow-up | `gemini-3-flash-preview` (bench vs `claude-sonnet-4-6`) | thinking off | customer-facing; bench before promote |
| Semantic verify (optional) | `claude-haiku-4-5` | — | decorrelated family if added |
| Reply classify | none (regex) | — | works, free |

## 6. Cost projection (per 1,000 leads fully processed)
| Path | sonnet-4-6 | gemini-3-flash | flash-lite |
|---|---|---|---|
| Enrich signal+ICP | ~$9 | ~$1.6 | ~$0.8 |
| Draft | ~$6.8 | ~$1.2 (less w/ cache) | — |
- Against the **$300 Vertex credit**, effective LLM spend ≈ £0 for tens of
  thousands of leads. Batch mode halves it again. The £50 cap stays as a backstop.
- Real monthly volume is warm-up-capped anyway, so the win is mostly
  *amortisation* (enrich once, reuse) + *free-on-credit*, not raw £ saved.

## 7. What I need from you (doctrine §D — no invented credentials)
**A Gemini credential.** Two routes:
- **(A) Vertex AI** in `settlepay-502417` — guarantees the $300 credit applies;
  auth via the service account (ADC), global endpoint (avoids the +10% regional
  surcharge from 2026-07-01). More setup.
- **(B) Gemini API key** (AI Studio) billed to the same Cloud Billing account —
  simpler `google-genai` SDK; confirm the credit applies to it.
Recommend **A** (credit is certain). Tell me which and I'll wire it.

## 8. Build order
- **Apply-directly now (no Gemini key needed):** reservoir/top-up model + config
  (`READY_POOL_TARGET`), CSV export, generalise the cost function, scaffold the
  structured enrichment contract, build the bench harness.
- **Bench-first (needs Gemini key):** swap signal→Flash-Lite, draft→Flash — each
  single-variable vs the sonnet-4-6 champion on the frozen bench.
- **Pilot-first:** re-enrich the existing pool through the new ICP gate on 10–20
  leads, eyeball the discards, before a full sweep.
```
