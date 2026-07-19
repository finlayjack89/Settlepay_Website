# Credit reservoir — pipeline design (agentic-pipeline BOTH mode)

> Design pass over [credit-reservoir-plan.md](credit-reservoir-plan.md). Mode = BOTH:
> new stages (Places discovery, corporate cross-ref, Places/grounded enrichment)
> built inside the existing pipeline's conventions (one llm.py wrapper, spend ledger,
> reservoir, ICP gate). Prices verified live 2026-07-19; models per LLM_MODELS.md.
> **Not built yet — this is the Phase-3 checkpoint for user sign-off.**

## Purpose / unit of work
Unit = **one lead** moving discovery → corporate-classified → enriched → ICP-scored →
(pre-)drafted into the reservoir. "Correct" = a lead that is genuinely ICP, correctly
classified corporate-vs-individual (the send-legality bit), contactable, and richly
enough enriched to personalise. Highest-stakes field = **subscriber_class** (decides
send-legality) — deterministic + fail-closed, never auto-flipped to "corporate".
Volume envelope = **batch** (hours), thousands of leads over 90 days.

## The economics (live-verified) — what actually spends the $300
| Lever | Unit price | Free tier | Role |
|---|---|---|---|
| **Places Text Search (New)** | **$32/1k** Pro · $35 Enterprise · $40 w/ reviews | 5k/mo Pro, 1k/mo Enterprise | **primary credit lever** — discovery |
| **Places Details (New)** | **$17/1k** Pro | (shared SKU tiers) | enrichment of qualified leads |
| Geocoding API | ~$5/1k | 10k/mo | address normalise for CH match |
| Gemini 3 Search grounding | **$14/1k** | **5k/mo free** | research — ~free at our volume |
| Gemini tokens (flash/lite) | $0.25–0.50/1M | — | negligible |
| MillionVerifier | £0.003/verify | — | 💷 cash (not credit) |
**Consequence:** the credit is spent on **Places**; grounding + tokens are ~free.
So the design's cost discipline is entirely about **Places call volume × field-mask
tier**. Two-phase Places: cheap Text Search (Pro fields only) at discovery; the
expensive Details/reviews call ONLY on leads already confirmed corporate + fit.

## GCP service map (what each does, and its credit role)
| Service | Use | Credit? |
|---|---|---|
| **Places API (New)** | Text Search (discovery) + Place Details (enrich) | ★ primary spend |
| **Geocoding API** | normalise Places address → postcode for CH matching | minor |
| **Vertex AI (Gemini)** | ICP-fit, signal, drafting (shipped) + grounded research | ~free |
| **Gemini Search grounding** | per-lead research (does-it-take-card, news, owner) | ~free (5k/mo) |
| **Cloud Run Jobs** | run-to-completion batch sweeps (discover/enrich thousands) | compute (minor) |
| **Cloud Scheduler** | pace the credit over 90 days (daily budgeted job) | ~free |
| **Secret Manager** | Places API key (shipped for other secrets) | free |
| **Supabase Postgres** | the reservoir (source of truth) — unchanged | n/a |
| Cloud Storage (opt) | raw Places/grounding responses as provenance | minor |
| BigQuery (skip) | reservoir analytics — Postgres suffices; avoid sprawl | — |

## Stage graph (new + modified)
| # | Stage | Role | Model class / API | Output contract | Fail direction |
|---|---|---|---|---|---|
| 1 | **Places discovery** | find local ICP businesses over a town×vertical grid | Places Text Search (Pro fields only) | {place_id,name,website,addr,locality,types} | n/a (API); dedup by place_id + vs leads |
| 2 | **Corporate cross-ref** | classify emailable(corporate) vs research-only | deterministic match + CH API + flash-lite disambig | subscriber_class enum | **fail-CLOSED**: unmatched/ambiguous → research-only, never sent |
| 3 | **Phone drop** | strip phone fields before persist | deterministic post-processor | — | hard invariant |
| 4 | **Places Details** (corp+fit only) | reviews/hours/rating/price → richer signal | Places Details (paid) | {rating,reviews_summary,hours,price_level} | skip on error (fail-open, logged) |
| 5 | **Grounded research** (corp only) | does-it-take-card? news? owner? | Gemini-3 flash + Search grounding | structured signals + source URLs | fail-open → factual signal |
| 6 | **ICP-fit gate** (enhanced) | qualify/disqualify + signal | flash-lite, JSON (shipped) | {icp_fit,already_card,size,signal,conf} | negative → discard before draft spend |
| 7 | **Email verify** | deliverable contact | Firecrawl + MillionVerifier (shipped) | tier enum | no tier → discard |
| 8 | **Reservoir rank** | tier by fit×richness; freshness stamp | deterministic | rank, ready flag | — |
| 9 | **Pre-draft** | touch-1 + follow-up | gemini-3-flash-preview (shipped) | body + envelope-pass | envelope fail → retry → discard |

Decorrelation: every generator is Gemini; the eval/judge role stays `claude-haiku-4-5`
(different family). Grounding text + Places data are **enrichment ground truth**; model
syntheses of them never re-enter as *verified* ground truth (doctrine-6 membrane), and
retrieved web text is treated as data, never instructions (doctrine 3.7).

## Verification ladder (new stages)
1. **Deterministic** — place_id dedup; exact name+postcode CH match; phone-strip; email
   regex/domain; envelope check. Free, first.
2. **Cheap model** — flash-lite disambiguation ONLY on fuzzy CH matches; ICP-fit gate.
3. **Grounded** — grounding returns source URLs → stored as provenance; dynamic-retrieval
   threshold so we only pay when the web actually grounds.
4. **Human queue** — ambiguous corporate matches above a confidence band; the operator
   confirms before such a lead is ever sendable. G_SEND stays human-only.

## Infrastructure to add (before any volume run)
1. **Credit-budget tracker** — SEPARATE from the £50 cash cap (that's MillionVerifier).
   A `$300 / 90-day` budget: per-run hard ceiling, daily pacing target, burn-down vs the
   clock, surfaced on the dashboard. Batch jobs get default cap + un-overridable ceiling +
   dry-run (doctrine 9).
2. **Cost-function extension** — register Places SKUs (per-1k by tier) + grounding (per-1k,
   Gemini-3 rate, 5k/mo free) as non-token billables in the ONE cost function; unknown-SKU
   loud fallback.
3. **Places call wrapper** — one instrumented wrapper: enforces the field-mask tier per
   call-site (Pro at discovery), logs SKU + units + cost, token-bucket admission, retries
   once. No raw Places calls anywhere else (lint convention).
4. **Places API key** — per-workload, human-provisioned, API-restricted to Places+Geocoding,
   in Secret Manager. (I never invent keys.)
5. **Cloud Run Job + Scheduler** — the batch sweep as a run-to-completion Job, paced daily
   by Scheduler within the credit budget; checkpoint/resume per lead; per-item ledger.

## Compliance invariants (unchanged, load-bearing)
Corporate-only send; individual/unknown = research-only, NEVER emailed (stage 2 fail-closed).
No phones persisted (stage 3). check_suppression before every send. ICP-fit before draft
spend. G_SEND human-only; warm-up caps; kill switch. Sole-trader-heavy ICP means stage-2 is
the difference between legal and not.

## Credit allocation (rough, 90 days, to pace)
| Initiative | Est. credit | Yield |
|---|---|---|
| Places Text Search discovery (~7k @ $32) | ~$220 | 7k local candidates |
| Places Details on qualified subset (~3k @ $17) | ~$50 | rich data on the corporate+fit ones |
| Geocoding | ~$5 | clean CH matching |
| Grounding | ~$0 (within 5k/mo free) | research on corporate leads |
| Gemini tokens (enrich/draft) | ~$5 | signals + thousands of drafts |
→ ~$280 of $300, yielding thousands of enriched, classified, pre-drafted leads.

## Build order (each a reviewable increment)
1. Infra skeleton: credit-budget tracker + cost-fn Places/grounding SKUs + Places wrapper
   (apply-directly; no volume).
2. Places discovery stage (dry-run on ONE town×vertical, ≤20 results — pilot).
3. Corporate cross-ref + phone-drop (pilot; eyeball the corporate/individual split).
4. Places Details + grounded research on the qualified subset (pilot cost check).
5. Wire into the reservoir + rank; Cloud Run Job + Scheduler pacing.
6. Bench/pilot end-to-end on ~50 leads; measure cost/lead vs the envelope; then scale.

## ICP reframe (2026-07-19, operator steer) — LOAD-BEARING
The ICP is **businesses that bill AWAY from a fixed till** — mobile, remote,
appointment/job- or invoice-based — for whom an online branded card page + invoicing
is NEW infrastructure. **NOT** fixed-till retail (shops, salons, barbers, cafes): they
already take card in person at a counter, so an online page is redundant. Encoded in:
- the ICP-fit gate (`payment_context`: invoice_remote=fit / fixed_till_retail +
  online_ecommerce = disqualified) — live-verified: mobile plumber & auctioneer
  qualify, barber & cafe rejected;
- discovery targeting (dropped hair&beauty/personal-services SICs; kept trades,
  clinics, professional/advisory; auctioneers by name).
So the Places grid targets **invoice/mobile verticals × towns**, and the field-mask
(business types) skews toward trades/clinics/advisory, not retail.

## Open decisions / what I need from you
- **Places API key** (you're creating it) — Places+Geocoding restricted → Secret Manager.
- Confirm **grounding price on Vertex** vs AI Studio at bind time (docs show $14/1k Gemini-3
  AI-Studio; one Vertex source said $35 — I'll verify live before enabling).
- **Town×vertical grid**: which UK towns + which ICP verticals, and the discovery volume
  cap per run (drives credit pace).
- Reservoir target size (currently 150 for the send-pool; the research reservoir can be far
  larger since it's decoupled).
