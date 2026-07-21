# Recon — Easy Live Auction (easyliveauction.com)

Auction-platform lead source, Phase 0–1. **No scraping written; this is recon only.**
Investigated 2026-07-21. Stop-and-review checkpoint per the brief.

---

## TL;DR — the one decision that gates everything

The technically-cleanest extraction (sitemap → static profile pages → JSON-LD) is
**trivial** and **permitted by robots.txt**. But **Easy Live Auction's Site Usage Terms
explicitly prohibit automated data collection without their written consent.** The Terms
override the robots.txt permission. So the question isn't *can we technically* — we
easily can — it's *are we allowed to*, and as written, **we are not, without consent.**

The good news: ELA is only a **seed list**. The only thing it uniquely tells us is *which
auctioneers exist and that they use a bidding-only platform* (the SettlePay wedge).
Everything we actually email on — their own website, how they take payment, their
directors, a named email — comes from the **auctioneers' own sites + Companies House**,
which the existing pipeline already gathers lawfully. That lets us quarantine the
ToS-restricted step (getting the ~448 names) from the enrichment we already do.

**Recommendation: do NOT auto-scrape ELA as it stands. Pick a lawful way to obtain the
seed list (options in §6), then feed those names into the existing enrichment chain.**

---

## Phase 0 — how a new source plugs into the current pipeline

The pipeline is a demand-pulled chain of stages, each idempotent, sharing one Postgres
schema (`outreach`). An auction source is a new **discovery** front-end that emits leads
in the exact shape the Places source already does — then the *entire* rest of the chain
is reused unchanged:

```
[NEW: auction Source] ─┐
                       ├─> leads (discovered) ─> crossref ─> enrich ─> decision_makers ─> draft ─> review ─> send
[Places Source] ───────┘   (PECR gate:          (own site   (CH officers   ("Dear <name>," +
[Companies House] ─────┘    name+postcode→CH →   scrape →     → verified     payment-method hook)
                            corporate/individual  payment      named email)
                            + company number)     signal +
                                                  ICP fit)
```

- **Data model** (`outreach.leads`): `company_number` (PK; synthetic `PLACE:<id>` /
  `URL:<domain>` when off-register), `company_name`, `registered_address` jsonb
  (postcode, website, categories, source query…), `subscriber_class`
  (corporate/individual/unknown — the PECR gate), `state`, `source`, `domain`
  (dedupe key). Enrichment, officers, drafts, sends, suppressions, audit_log hang off
  `company_number`.
- **Where it plugs in:** a new `source='easylive'` discovery step that inserts auctioneer
  records with `state='discovered'`, `subscriber_class=null` (so `crossref` classifies
  them), `registered_address` carrying postcode + categories + logo, and `domain=null`
  (enrichment resolves the real site). **An ELA auctioneer record is the same shape as a
  Places record**, so crossref/enrich/decision_makers/draft need zero changes.
- **Reuse, do not duplicate:** `crossref.match_company` (name+postcode → Companies
  House), `enrich.discover_and_run` (own-website resolve + scrape + verify + ICP fit),
  `decisionmakers.run` (officers → named email), `draft` (the v2.5 playbook, greeting
  now "Dear <business>," / "Dear <first name>,"). The auction source only has to produce
  clean seed records.
- **Language/deps:** Python 3.12, `httpx`, `psycopg`, `dotenv`. Adding this source needs
  **no new runtime dependency** for route (a) — a static fetch + stdlib `re`/`json`
  parse of the JSON-LD is enough. (An HTML-DOM parser like `selectolax` would only be
  nice-to-have; not required.)

---

## Phase 1 — site architecture recon

### robots.txt (https://www.easyliveauction.com/robots.txt)
```
User-agent: ClaudeBot        Disallow: /        ← named AI crawlers fully blocked
User-agent: Claude-Web       Disallow: /
User-agent: MJ12bot          Disallow: /
User-Agent: *
  Disallow: /api/            ← internal JSON endpoints OFF-LIMITS
  Disallow: /manage/  /auctioneer/  /auctioneer_live/  /live_v2/  /components/
  Disallow: */print-catalogue*  */share-email*  */login*
Sitemap: https://www.easyliveauction.com/sitemap-index.xml
```
Read carefully: `/api/` and `/auctioneer/` (**singular** — the bidding/management console)
are disallowed, but `/auctioneers/` (**plural** — the public directory profile pages) is
**not** listed, i.e. permitted for `*`, and the sitemap advertises exactly those pages.
Note also they **explicitly block ClaudeBot/Claude-Web** — a clear "no AI crawlers"
signal even though a generic UA is allowed the directory.

### Site Usage Terms (/legal/site-usage-terms/) — the binding constraint
> "You must not conduct any systematic or automated data collection activities
> (including without limitation scraping, data mining, data extraction and data
> harvesting) on or in relation to this website without EASY LIVE AUCTION'S express
> written consent."
> "The automated and/or systematic collection of data from this website is prohibited."
> Users must not "reproduce, duplicate, copy or otherwise exploit material on this
> website for a commercial purpose."

This is a blanket prohibition and it **supersedes** the robots.txt allowance. A sitemap
existing does not grant scraping rights — it is for search indexing; the Terms still bind
a commercial user. **Automated extraction of ELA, as the Terms stand, requires their
written consent.**

### Discovery surface (what's exposed)
`sitemap-index.xml` → 8 child sitemaps: main, upcoming-auctions, past-auctions (×2),
upcoming-lots (×3), and **`sitemap-auctioneers.xml`**.
- **`sitemap-auctioneers.xml` = 448 auctioneer profile URLs**, pattern
  `https://www.easyliveauction.com/auctioneers/<slug>/`, `<lastmod>` daily. This is the
  complete directory — a clean, bounded list, no pagination to fight.

### A profile page (`/auctioneers/<slug>/`)
- **Static, server-rendered HTML** (~29 KB). Backend is ColdFusion (`CFID`/`CFTOKEN`/
  `JSESSIONID=…​.cfusion` cookies). **All content is in the raw response — no JS
  rendering, no XHR needed.** → a headless browser (Playwright) is **unnecessary**.
- **Behind Cloudflare** (`server: cloudflare`, `cf-ray`), but a single polite request
  with a custom User-Agent was served 200 with no challenge/JS-interstitial/403. No
  evidence of aggressive bot-blocking on the directory pages (volume behaviour untested,
  and untested on purpose — we are not scraping).
- **Structured data: two JSON-LD blocks** — `BreadcrumbList` and, cleanly, a
  `localBusiness`:
  ```json
  { "@type": "localBusiness",
    "name": "1888 Auctioneers",
    "description": "Football & Sporting, Programme & Memorabilia specialists",  // SPECIALISM
    "logo": "https://content.easyliveauction.com/auctioneer/images/logos/....JPG",
    "url":  "https://www.easyliveauction.com/auctioneers/1888auctioneers/",
    "telephone": "01212 709449",          // MUST be dropped — no phones, ever (compliance)
    "address": [{ "streetAddress": "...", "postalCode": "B33 0SG",
                  "addressCountry": "United Kingdom" }] }   // postcode = the CH cross-ref key
  ```
  (HTML entities are hex-encoded, e.g. `&#x20;` — unescape on parse.)

### Fields available per auctioneer, and where each goes
| Field (from JSON-LD / page) | Present? | Pipeline use |
|---|---|---|
| Business name | ✅ | seed → crossref name match |
| Postcode | ✅ | crossref postcode match → Companies House |
| Street address / country | ✅ | context |
| Specialism / categories | ✅ (`description`, `og:description`, body) | scoring (category value); email hook |
| Logo URL | ✅ (`content.easyliveauction.com`) | future branded mock |
| **Their own website** | ❌ **not exposed** (ELA keeps bidders on-platform) | resolved by existing enrichment from name+postcode |
| Next-auction date | ⚠️ page body "Upcoming" block, often empty | scoring (frequency); email hook — needs HTML parse, not in JSON-LD |
| Telephone | ✅ but **never persisted** | dropped at parse (compliance) |

The two most valuable email hooks the brief wants — the **own website** and the **"how do
winners pay" sentence** — are **not on ELA at all**; they come from the auctioneer's own
site via the enrichment stage. ELA's real contribution is *name + postcode + specialism +
the fact they're on a bidding-only platform*.

---

## §5 Extraction routes assessed

| Route | Works? | robots | ToS | Verdict |
|---|---|---|---|---|
| (a) static HTTP + JSON-LD/HTML parse of `/auctioneers/<slug>/` via sitemap | ✅ trivially (static, structured) | ✅ permits `/auctioneers/` | ❌ prohibits automated collection | lightest by far, but ToS-blocked |
| (b) internal JSON `/api/` endpoint | likely | ❌ **disallowed** | ❌ | reject |
| (c) headless browser (Playwright) | overkill | n/a | ❌ | reject — content is static, so no reason to |

Technically the answer is unambiguous: **(a)** — no API, no browser, a ~50-line
`httpx` + `json`/`re` parser over 448 sitemap URLs. The blocker is not technical.

---

## §6 Recommendation

**Do not auto-scrape ELA as the Terms stand.** Instead, separate the ToS-restricted step
(obtaining the seed list) from the enrichment we already do lawfully, and choose one:

1. **Seek written consent from Easy Live Auction** (the Terms explicitly allow automated
   collection *with* it). ELA is itself a plausible SettlePay conversation — a
   bidding-only platform whose auctioneers all have the payment gap — so this could be a
   partner/prospect approach, not just a permission ask. Cleanest if it lands.
2. **Seed the list without automated collection of ELA.** The 448 names are a public
   directory; a person compiling the names (not a bot harvesting the site) is a
   different act from "systematic automated collection". Those names then go through the
   existing enrichment (which touches the auctioneers' **own** sites + Companies House,
   **not** ELA).
3. **Use a friendlier source for the seed list.** UK auctioneer trade bodies /
   directories — SOFAA, NAVA Propertymark, RICS, the Antiques Trade Gazette — may list
   the same houses under terms that don't forbid automated access. Recon those next; the
   enrichment chain is identical regardless of where the names come from.

Whichever seed route: build the **`Source` adapter interface** now (so the-saleroom /
BidSpotter / i-bidder slot in later), but have the Easy Live adapter's *fetch* step be
consent-gated — it stays a stub that reads a supplied name list until route 1/2/3 is
settled, rather than hitting ELA.

**For the other three platforms** (the-saleroom.com, bidspotter.co.uk, i-bidder.com):
each needs its own robots + Terms check before any adapter — do not assume ELA's answer
carries over.

---

## Cross-cutting compliance notes (carried from the existing pipeline)
- **PECR gate is reused:** crossref classifies each auctioneer corporate vs individual
  from its Companies House entity type; individual (sole-trader/partnership) auction
  houses are research-only, never cold-emailed. `pecr_class` already exists as
  `subscriber_class`.
- **No phones, ever** — the JSON-LD `telephone` is dropped at parse, matching the rule
  the Places wrapper already enforces.
- **Named-contact GDPR** (if we resolve a director email) is the full art. 14 / art. 21
  regime already built in `decisionmakers.py` + the named-send footer — same gates
  (`DECISION_MAKER_ENABLED`, privacy-notice, MillionVerifier credits).
- **Legitimate-interest assessment + privacy-notice link** are required before emailing;
  documented in the outreach README go-live TODOs.

---

## Status
Phase 0 ✅ · Phase 1 ✅ · **Phases 2–6 NOT started** (blocked on the §6 seed-source
decision — deliberately, per the brief's "do not write scrapers before completing Phase
0 and 1; stop and show me after Phase 1").
