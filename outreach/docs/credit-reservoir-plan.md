# Credit-funded reservoir — design brief (input for the /agentic-pipeline run)

> This is the GENERAL IDEA, at design-brief altitude. The detailed stage/model/
> verification design comes from re-running the agentic-pipeline skill against this.
> Nothing here is built yet.

## Goal
Convert the **$300 GCP credit (90-day expiry)** into a durable asset: a large,
deeply-enriched, pre-qualified, compliant, pre-drafted **lead reservoir** —
decoupled from send pace by the reservoir architecture already shipped. Front-load
the expensive acquisition now (on the credit); draw it down over months at warm-up
pace.

## The core economic insight (drives everything)
Gemini **tokens** are too cheap to spend $300 in 90 days (our LLM cost is ~£1–2/mo).
The credit levers that cost real money per call are the **paid GCP APIs**, and they
happen to be exactly what makes leads better:
- **Places API** — discovery + local data (~$30–50 / 1k rich lookups) ← VERIFY LIVE
- **Gemini + Google Search grounding** — per-lead research (~$35 / 1k grounded) ← VERIFY LIVE
So "spend the credit" == "build a big, rich reservoir". Don't burn credit for its
own sake; every call must produce durable lead value.

## New / expanded pipeline (the reservoir-fill half)
1. **Discovery — dual-source**
   - (existing) Companies House SIC sweep → registered companies.
   - (new) **Places API** across a UK town × ICP-vertical grid → local small
     businesses with website, rating, hours, location, place_id.
   - Dedup + merge into `outreach.leads`.
2. **Corporate cross-reference (the PECR spine)**
   - Resolve Places businesses to a Companies House registered entity
     (name/postcode match) → set `subscriber_class`.
   - **Corporate (Ltd/LLP) = emailable; sole-trader/unknown = research-only, NEVER
     sent.** This is the load-bearing compliance gate — the ICP skews to sole
     traders, whom PECR protects.
   - Drop all phone fields (no phones persisted, ever).
3. **Enrichment — layered, credit-funded**
   - Website resolve (Places gives it; Firecrawl fallback).
   - Places Details: reviews, rating, hours, status, price level, locality.
   - **Gemini grounded research**: visibly takes card? recent news? owner name?
     services? → structured signals (spend the grounded call only on corporate+fit
     leads, to conserve credit for value).
   - Email discovery + MillionVerifier verify.
   - **ICP-fit gate (already built)** — now fed richer inputs → higher precision.
4. **Reservoir organisation (the lead list)**
   - All signals + provenance in leads/enrichment; CSV export (shipped).
   - **Tier/rank** leads by fit confidence × data richness so the best draft/send
     first. Freshness stamps (re-verify contacts >90 days).
5. **Pre-drafting (cheap, front-loaded)**
   - Draft touch-1 + follow-up for corporate+fit leads (Gemini flash); queue for
     batch human review, so an approved backlog is ready when sending scales.
6. **R&D / quality loop (modest credit)**
   - A/B prompt variants; edit-ratio scoring; extend the bench into a Gemini-judged
     eval harness; optional prompt-review loop.

## Compliance invariants (unchanged — must survive the expansion)
- Corporate-only send; individual/unknown = research-only, never emailed.
- No phones persisted. check_suppression before every send. ICP-fit before draft spend.
- G_SEND human-only; warm-up caps; kill switch; body_original immutable.
- Places/grounding data is enrichment ground truth; model syntheses never re-enter
  as *verified* ground truth (doctrine membrane).

## Key infra the design must add
- **Credit-budget tracker, separate from the £50 cash cap.** MONTHLY_SPEND_CAP_GBP
  is CASH (MillionVerifier). The $300 credit is a separate 90-day budget — needs its
  own ledger + pacing (hard per-run/per-day ceilings, doctrine 9) so we neither
  under-use nor blow it, and a burn-down vs the 90-day clock.
- **Register Places + grounding pricing in the cost function** before the first call
  (doctrine 8 — no silent unpriced calls). New non-token billables (Places SKUs,
  grounding units) with their native units.
- **Per-workload API key** for Places (human-gated; I never invent keys).

## Open decisions for the agentic-pipeline design
- Places grid strategy: which towns × verticals, volume, ranking, dedup vs CH.
- Corporate-match reliability (fuzzy name/postcode → subscriber_class) and its
  fail direction (unmatched → research-only, fail-closed on send).
- When to spend the grounded call (corporate+fit only?) to conserve credit for value.
- Reservoir target size + tiering formula.
- 90-day credit pacing model + the burn-down telemetry.
- Model/class assignments (re-run the model-landscape research): grounding-capable
  Gemini model + verify grounding is supported on Vertex; keep signal/ICP on
  flash-lite, drafting on flash-preview, eval judge on a decorrelated family.

## Not in scope for this phase
Actually sending at scale (still G_SEND-gated + warm-up-paced); Clay (parked).
