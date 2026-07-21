# Auction-platform lead source

Turns public auction-platform listings into enriched, scored SettlePay leads.

**The wedge:** platforms like Easy Live Auction run the *bidding* only — the auctioneer
still invoices the winner and collects payment itself, usually by bank transfer or a
manual card link. So every auctioneer listed is a pre-qualified business with exactly
SettlePay's pain: no online card page, reconciliation done by hand.

## What it does

```
Source (per platform) → enrich (REUSES the outreach pipeline) → score → dedupe → CSV+JSON
```

1. **Source** — discovers auctioneers on a platform and emits raw records
   (name, postcode, categories, logo). One adapter per platform behind a clean interface.
2. **Enrich** — reuses the outreach pipeline's primitives, not reimplemented:
   Firecrawl website resolution, page scrape + the **payment-method detector** (the exact
   "pay by bank transfer" sentence), the Gemini ICP-fit signal, the Companies House PECR
   gate + directors, and MillionVerifier-confirmed decision-maker emails.
3. **Score** 0–100 (manual-payment signal weighted highest; non-corporate capped at 25).
4. **Dedupe** by website domain → Companies House number → name+postcode.
5. **Output** CSV (spreadsheet) + JSON (tool / drafting hand-off), highest score first.

## Setup

Runs inside the existing `outreach` project — same `.env`, same venv. Keys reused from
`outreach/.env` (nothing new to add for Easy Live):

| Key | Used for | Required |
|---|---|---|
| `COMPANIES_HOUSE_API_KEY` | PECR gate + directors | yes |
| `FIRECRAWL_API_KEY` | resolve each auctioneer's own website | yes (for websites) |
| `MILLIONVERIFIER_API_KEY` | confirm decision-maker / generic emails | yes (for emails) |
| `GEMINI_PROJECT` | ICP-fit signal | optional |

Auction-specific knobs (all optional, sane defaults) — set in `.env`:
`AUCTION_RATE_LIMIT_SECONDS` (2.5), `AUCTION_MAX_RETRIES` (3), `AUCTION_CACHE_DIR`,
`AUCTION_SAMPLE_SIZE` (25), `AUCTION_OUTPUT_DIR`, `AUCTION_USER_AGENT`.

## Run

```bash
# prove on a small sample first (writes CSV+JSON, no DB writes)
python -m outreach.auctions.run --platform easylive --sample

python -m outreach.auctions.run --platform easylive --limit 100
python -m outreach.auctions.run --platform all --limit 50          # every registered source
python -m outreach.auctions.run --platform easylive --sample --ingest   # + push to DB drafting
```

Output lands in `AUCTION_OUTPUT_DIR` (default `outreach/auction_output/`). An on-disk HTTP
cache makes re-runs cheap and idempotent — delete the cache dir to force a refetch.

## Adding a new platform

1. **Recon first** — check the platform's `robots.txt` AND Terms of Use; write findings to
   `docs/recon/<platform>.md`. Do not skip this: terms differ per site.
2. Write `sources/<platform>.py` subclassing `Source`, implementing `iter_auctioneers()`
   and setting `terms_note`.
3. Register it in `sources/__init__.py:REGISTRY`.
   Everything downstream (enrich/score/dedupe/output) is platform-agnostic — no other
   change.

## Legal notes (READ before sending)

- **Terms of Use.** A platform's Terms may prohibit automated collection (Easy Live's do —
  see `docs/recon/easyliveauction.md`). Obtaining the seed list is the operator's
  responsibility; the recon docs record each platform's position. This tool runs at the
  operator's direction.
- **PECR.** Only a confirmed **corporate** subscriber (Ltd/LLP) is cold-emailable; sole
  traders / partnerships are classified `individual` and flagged research-only — never
  cold-emailed. This is the same gate the pipeline enforces.
- **Named individuals = full UK GDPR.** A decision-maker email is personal data: a
  legitimate-interest assessment and a privacy-notice link are required, and every send
  to a named person must carry the art. 14 transparency footer (already built into the
  pipeline's send path). Turn on decision-maker email resolution knowingly.
- **No phones, ever.** Telephone numbers exposed by a platform are never captured.
- **Opt-out.** The drafting hand-off carries sender identity + a one-click reply-based
  opt-out, and suppression is re-checked before every send.
