# Outreach system — assessment (where it wastes, where it fails, what to improve)

*Honest engineering review of the pipeline as built. The mechanism is sound and
compliant; the value leaks are mostly in **targeting** and **contact discovery**,
and the highest-consequence risks sit at the **send** step that isn't live yet.*

## The funnel, as measured

Real numbers from the live `outreach` schema (SIC 68310, estate agents — the first
vertical run):

| Stage | Count | % of discovered |
|---|---|---|
| Discovered (Companies House) | 50 | 100% |
| PECR-cleared (corporate) | 50 | 100% |
| Website resolved | 5 | 10% |
| Contact email found | 3 | 6% |
| Email verified (MillionVerifier `ok`) | 3 | 6% |

So **~94% of the work (and API spend) produced nothing contactable.** Everything
below is ranked by how much of that loss it explains and how cheap it is to fix.

---

## 1. Targeting is the dominant bottleneck (biggest waste, cheapest fix)

**What:** "Active company in SIC X" is a weak proxy for "real trading business we
can email." Most companies returned for SIC 68310 are property-holding / SPV /
dormant LTDs with no website and no reachable inbox — they exist on paper only.
We discover 50, and 47 are correctly discarded as unreachable.

**Cost:** every discarded lead still consumes a Firecrawl search (~2 credits) and
up to 5 httpx fetches + up to 3 Firecrawl scrapes before we learn it's a dead end.
The spend happens *before* the yield is known.

**Fix (in order of leverage):**
- **Pre-filter at discovery** on signals of a trading business: exclude
  `accounts.accounts_category` of `DORMANT`/`NO_ACCOUNTS`; require a recent
  confirmation statement; drop names matching `PROPERTY|INVESTMENT[S]|HOLDINGS|SPV|
  NOMINEE`. This is free and removes most of the shells before we spend a credit.
- **Target SICs that correlate with a web presence and card/invoice payments**
  (accountants, agencies, clinics, trades, hospitality) rather than estate agents,
  many of whom are appointed-representative SPVs. (This review seeded a second
  vertical — accountants, SIC 69201 — precisely to measure that; see the dashboard's
  *Yield by vertical* panel for the side-by-side.)
- **Consider a web-first lead source** (a trade-body member directory, Google Maps/
  Places by category+town) where *every* entry has a site by construction. CH then
  becomes the enrichment/verification layer, not the discovery layer.

## 2. Contact discovery is brittle and spends before it yields

**What:** discovery = httpx GET on `/`, `/contact`, `/about` (+2) → regex emails →
Firecrawl fallback. It misses the common cases for small-business sites:
- contact **forms** with no exposed address (Wix/Squarespace/GoDaddy templates),
- **obfuscated** email (image, `info [at] domain`, Cloudflare email-protection),
- email only in **JS-rendered** content or `schema.org`/JSON-LD metadata.

**Cost:** we pay for a search + multiple fetches + a Firecrawl render and still end
at `no_email → discarded` for businesses that are, in fact, reachable.

**Fix:**
- **Guess-and-verify before scraping:** derive `info@`, `enquiries@`, `hello@` from
  the resolved domain and verify those with MillionVerifier *first*. If one is
  `ok`, skip scraping entirely — cheaper and higher-yield than parsing HTML.
- Parse `mailto:` links and JSON-LD `Organization.email`; de-obfuscate the common
  `[at]`/`(at)` patterns.
- Treat **"has a working contact form"** as a separate reachable channel rather
  than a discard (a form submission is a valid first touch).

## 3. `ok`-only verification silently discards reachable mailboxes

**What:** `verify_email` counts only MillionVerifier `result == "ok"` as verified;
`catch_all` and `unknown` are discarded. A large share of legitimate small-business
inboxes sit on **catch-all** Microsoft 365 / Google Workspace tenants and come back
`catch_all`.

**Cost:** real, deliverable businesses are thrown away as "unverifiable." On a
catch-all-heavy vertical this can be the single biggest filter after targeting.

**Fix:** make `catch_all` a distinct **"risky-but-sendable"** tier (send at lower
volume / with extra spot-checking) instead of a discard. This is a policy lever the
playbook should own; right now the mechanism forecloses it at the code level.

## 4. No retry/backoff — transient failures become permanent discards

**What (observed during this review):** the enrich loop held **one DB connection
open across the whole slow batch**; the Supabase pooler dropped it mid-run and the
batch died (`SSL SYSCALL error: Can't assign requested address`). Separately, any
transient HTTP error on a site resolves to `website=None → discarded` with no retry.

**Cost:** a momentary network blip permanently discards a good lead; a dropped
connection loses an entire run's work.

**Fix (partly done):** enrichment now does **all slow network work first, then
writes in one short transaction** (`_gather` / `_persist` split), so the DB
connection is held only for milliseconds — the pooler can't time it out mid-batch.
Still to do: retry-with-backoff on transient HTTP, and a `transient_failed` lead
state for re-attempt instead of immediate discard.

## 5. The personalisation "signal" is a placeholder (biggest reply-rate lever, deferred)

**What:** the whole premise of agentic outreach is a specific, relevant opener.
Today the `signal` is factual only ("Firm — Accountants in Ipswich"); the real
LLM-derived signal (what the business does, a genuine hook) is the **deferred
playbook + `api` LLM provider**, not built.

**Cost:** until it lands, drafts are generic. This is the largest lever on reply
rate and it's intentionally out of the current remit — but it's the gap between
"compliant plumbing" and "outreach that works."

---

## Highest-consequence latent risks (must exist before G-SEND flips)

These don't waste money today; they would **burn the whole funnel at the last step**
the moment live sending is enabled.

- **Deliverability / warmup.** Sending cold from one fresh domain mailbox with no
  warmup, SPF/DKIM/DMARC and reputation will land in spam. The per-inbox cap (5/day)
  exists; warmup, authentication and domain reputation do not. **This is the single
  highest-consequence missing piece.**
- **Reply / bounce / unsubscribe ingestion.** The `replies`/`suppressions` tables
  exist but nothing reads the sending mailbox to feed them. Without it we'd (a)
  re-contact people who asked to stop (PECR breach + reputational damage), (b)
  can't compute bounce rate (a graduation metric), (c) keep hard-bouncing and
  trashing reputation. **Required before any real send.**
- **Spend/usage tracking.** We cap requests per run but don't record Firecrawl /
  MillionVerifier consumption anywhere — usage is invisible until a quota is hit.
  Record per-run API usage to a `runs` table and surface it on the dashboard.

## Throughput ceiling

Every draft needs a human decision before send, so **send rate = review rate**.
That's correct for now (compliance + quality), but it caps scale. The
graduation-to-auto-send thresholds are defined; the spot-check sampling + auto-send
path that would relax the human gate per-vertical is not built.

---

## What's solid (so the above is in proportion)

- **PECR firewall is fail-safe and audited:** only an explicit corporate-type
  allowlist is contactable; everything else is suppressed, with a lawful-basis
  audit row per decision.
- **Send is hard-gated:** no live send without a human setting `G_SEND`; four guards
  (kill switch, individual block, suppression check, per-inbox cap) run before any
  send path is even reached.
- **`body_original` is immutable;** human edits go to `body_final`, giving a clean
  edit-diff as the training signal for the future playbook.
- **Clean separation of schemas:** the pipeline never touches the website's `public`
  tables; it only reads them to suppress existing enquirers.

## Recommended next steps (priority order)

1. **Targeting pre-filter** (free, biggest yield gain) — exclude dormant/SPV/holding
   companies at discovery; prefer web-present verticals.
2. **Guess-and-verify `info@` before scraping** + accept `catch_all` as a tier
   (cheaper, recovers reachable businesses).
3. **Reply/bounce/unsubscribe ingestion** (required before live send).
4. **Domain warmup + SPF/DKIM/DMARC** on the dedicated sending domain (required
   before live send).
5. **Real personalisation signal** (the deferred `api` provider + playbook) — the
   biggest reply-rate lever, once 1–4 make the funnel worth sending into.
