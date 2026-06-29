# Outreach system — assessment (where it wastes, where it fails, what to improve)

*Honest engineering review of the pipeline as built. The mechanism is sound and
compliant; the value leaks are mostly in **targeting** and **contact discovery**,
and the highest-consequence risks sit at the **send** step that isn't live yet.*

## The funnel, as measured — same machine, different lead sources

Real numbers from the live `outreach` schema. The first run targeted estate agents
(SIC 68310, no filters); subsequent runs applied the new targeting + guess-and-verify
to ICP verticals, to isolate how much of the loss is *targeting* vs *mechanism*:

| Vertical (SIC) | Discovered | Website resolved | Verified contact | Yield |
|---|---|---|---|---|
| Estate agents (68310, no filter) | 50 | 5 | 3 | **6%** |
| Hair & beauty (96020) | 12 | 7 | 1 | **~11%** |
| Dental practices (86230) | 12 | 12 | 5 | **42%** |
| Accountants (69201) | 18 | 18 | 9 | **50%** |

Same code, same spend per lead — **a 6–8× difference in yield purely from the lead
source.** On estate agents ~94% of the work produced nothing contactable; on
accountants/dental, ~half the batch became a real, verified, own-domain contact.
That's the headline: **the mechanism is fine; the lead source is the lever.**

Two secondary findings from the same runs:
- **`info@` guess-and-verify is now the cheapest, biggest contact source** — it
  supplied **11** verified contacts directly, with no page scrape at all.
- **Not all ICP verticals are equal.** Hair & beauty (in-person services) yielded
  far lower than accountants/dental — more sites are form-only or on catch-all
  mailboxes. That's precisely the `catch_all`-as-a-tier case in finding #3.

Everything below is ranked by how much of the remaining loss it explains and how
cheap it is to fix.

---

## 1. Targeting is the dominant bottleneck (biggest waste, cheapest fix)

**What:** "Active company in SIC X" is a weak proxy for "real trading business we
can email." Most companies returned for SIC 68310 are property-holding / SPV /
dormant LTDs with no website and no reachable inbox — they exist on paper only.
We discover 50, and 47 are correctly discarded as unreachable.

**Cost:** every discarded lead still consumes a Firecrawl search (~2 credits) and
up to 5 httpx fetches + up to 3 Firecrawl scrapes before we learn it's a dead end.
The spend happens *before* the yield is known.

**✅ Implemented (`targeting.py` + `find_leads`):**
- **Shell-name exclusion** before any paid discovery — drops
  `PROPERTY|HOLDINGS|INVESTMENTS|SPV|NOMINEE|BIDCO|…`-named companies.
- **ICP SIC sweep** — discovery defaults to verticals that correlate with a web
  presence + card/invoice payments (professional services, clinics & health, trades,
  in-person services). Measured: **accountants 50% / dental 42% vs estate agents 6%**.
- **Trading-age filter** (`incorporated_to`) to cull fresh shells, and **name-based
  discovery** (`name_includes`) for sectors with no clean SIC (auctioneers).
- **Optional dormancy gate** (`skip_dormant`) — one free CH profile fetch to skip
  `DORMANT`/`NO_ACCOUNTS` companies before spending a discovery credit.

**Still worth doing:** a **web-first lead source** (trade-body member directory,
Google Maps/Places by category+town) where *every* entry has a site by construction,
with CH as the enrichment/verification layer rather than discovery.

## 2. Contact discovery is brittle and spends before it yields

**What:** discovery = httpx GET on `/`, `/contact`, `/about` (+2) → regex emails →
Firecrawl fallback. It misses the common cases for small-business sites:
- contact **forms** with no exposed address (Wix/Squarespace/GoDaddy templates),
- **obfuscated** email (image, `info [at] domain`, Cloudflare email-protection),
- email only in **JS-rendered** content or `schema.org`/JSON-LD metadata.

**Cost:** we pay for a search + multiple fetches + a Firecrawl render and still end
at `no_email → discarded` for businesses that are, in fact, reachable.

**Two real failures caught in the accountants run** (and since hardened):
- A bookkeeping site exposed only a font designer's `impallari@gmail.com` and a font
  foundry's `team@latofonts.com` in its markup; the real contact lived on a *second,
  abbreviated* domain (`…@cardiffbas.com`). The picker grabbed the gmail.
- For another, the resolver returned a **Latvian company registry** (`nace.lursoft.lv`)
  instead of the company's own site, so it "found" `info@lursoft.lv`.

**✅ Implemented:**
- **Guess-and-verify before scraping:** `info@/enquiries@/hello@/contact@<domain>`
  are verified with MillionVerifier *first*; if one is `ok` we skip scraping
  entirely. In this review it supplied **11** verified contacts with no scrape —
  cheaper and higher-yield than parsing HTML, and it recovers contact-form-only sites.
- **Own-domain-only / no-freemail picking:** `pick_contact_email` rejects free-mail
  and third-party addresses and, when the domain is known, accepts only that domain
  (this is what fixed the `impallari@gmail.com` and `info@lursoft.lv` mis-picks); the
  registry was added to the resolver skip-list.

**Still worth doing:** parse `mailto:` / JSON-LD `Organization.email`; de-obfuscate
`[at]`/`(at)`; recognise an *abbreviated* own-domain (the `cardiffbas.com` case);
treat **"has a working contact form"** as a reachable channel rather than a discard.

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

**✅ Implemented:** enrichment now does **all slow network work first, then writes in
one short transaction** (`_gather` / `_persist` split), so the DB connection is held
only for milliseconds — the pooler can't time it out mid-batch. And `verify_email`
**retries once and degrades to `verify_error`** instead of raising, after a single MV
timeout aborted a whole batch during this very review.

**Still worth doing:** retry-with-backoff on transient *site* HTTP errors, and a
`transient_failed` lead state for re-attempt instead of immediate discard.

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

**✅ Done this review:** targeting pre-filter (#1), `info@` guess-and-verify +
own-domain picking (#2), DB-connection hardening + verify retry (#4). Measured lift:
estate agents 6% → accountants 50% / dental 42%.

**Next:**
1. **Accept `catch_all` as a "risky-but-sendable" tier** (#3) — small change, recovers
   reachable businesses; matters most for in-person verticals like hair & beauty.
2. **Reply/bounce/unsubscribe ingestion** — required before any live send (PECR +
   reputation + bounce-rate metric).
3. **Domain warmup + SPF/DKIM/DMARC** on the dedicated sending domain — required
   before any live send (deliverability).
4. **Spend/usage tracking** (`runs` table + dashboard) — make Firecrawl/MV cost visible.
5. **Web-first lead source** + `mailto`/JSON-LD parsing — push yield past 50%.
6. **Real personalisation signal** (the deferred `api` provider + playbook) — the
   biggest reply-rate lever, once the above make the funnel worth sending into.
