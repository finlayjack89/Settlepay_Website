# Recon — LiveAuctioneers · Invaluable

Investigated 2026-07-21. Adapters built: `outreach/auctions/sources/liveauctioneers.py`,
`outreach/auctions/sources/invaluable.py`.

Both are US-centric marketplaces with a UK tail. They work, but they are **thinner
sources than the ATG platforms** — expect a lower yield per credit, and read §"Worth
running?" before a full sweep.

---

## LiveAuctioneers (liveauctioneers.com)

**Access.** `robots.txt` is served normally and disallows `/auctioneers/` — the *legacy*
path. The live directory is `/auctioneer/directory/`, which is not disallowed. The page is
client-side rendered, so it still needs `get_rendered`.

**Discovery.** The **entire** directory is one page (~4,400 houses, 460 KB of markdown),
grouped under country headings. The `United Kingdom` block holds **~289** houses and is
the only part used — one rendered fetch gets the whole UK list.

```markdown
United Kingdom

- [1818 Auctioneers](https://www.liveauctioneers.com/auctioneer/8084/1818-auctioneers/)
- [1843 Diamonds](https://www.liveauctioneers.com/auctioneer/6621/1843-diamonds/)
…
All Around the World          ← the next country heading ends the section
```

The section ends at the first non-empty line that is not a list item. Source id is the
numeric house id from the URL.

**Profile.** Gives their own `About <name>` blurb (categories — again, *their* words only;
the site-wide category nav must never be read) and a full address. The address is taken
from the Google **static-map URL** the page builds (`?center=Junction%2036%20Auction%20
Centre%20Cumbria%20LA7%207FP%20United%20Kingdom`) rather than the visually-split address
lines — it is one clean string and more reliable to parse.

No website, no email exposed. Website resolution falls back to the enrichment stage, as
with Easy Live.

Verified live: `1818 Auctioneers → LA7 7FP / Cumbria`, `1843 Diamonds → B63 3TJ /
Halesowen`, `365 Consultancy Ltd → W1W 7LT / London`.

---

## Invaluable (invaluable.com)

**Access.** Cloudflare refuses a direct request outright (`Sorry, you have been blocked`),
so no robots.txt is readable either. Firecrawl fetches it normally.

**Discovery.** `/auction-house?page=N`, 100 entries a page, plus a **server-side country
filter**: `&countryName=United+Kingdom` → **~98** UK houses on page 1. That filter is worth
using rather than sweeping and discarding — Invaluable is overwhelmingly US, so an
unfiltered sweep would spend most of its credits on houses the PECR gate can never pass.

**Pagination trap:** past the end, the listing silently serves **page 1 again** rather than
an empty page. So the stop condition is "nothing *new* on this page", not "nothing at
all" — otherwise paging never terminates. Pinned by a test.

**Profile.** Their own bio under the `# <name>` heading (categories), and a town + country
as `#### ` lines. **No postcode**, no website, no email — so the Companies House match
leans on the business name alone, which is the weakest match this pipeline does.

Verified live: `A F Brock and Co Ltd → Stockport, cats: coins/jewellery/medals/stamps`.

---

## What the first sample run exposed (and fixed)

Invaluable's 5-lead sample "resolved" two websites, and **both were the wrong company**:

- `A J Cobern → cascobayauctions.com` — a Maine, USA auction house
- `A Victor Powell → worcesternews.co.uk/news/business/…` — a *news article about them*

That is not cosmetic: a wrong domain feeds the payment signal, the dedupe key and the
decision-maker email permutations for a different business. The thinner the source, the
likelier it is — Invaluable gives the resolver no postcode to disambiguate with.

Fixed in `auctions/enrich._name_matches_domain`: a distinctive word from the business name
must survive in the resolved domain, or the candidate is dropped with a note explaining
why. Generic words every auction house shares (*auctions, auctioneers, valuers, ltd, fine,
art, saleroom…*) do not count. When a name is all initials and generic words the guard
**abstains** rather than guessing, and the URL is kept with a note.

Checked against the 15 leads of the first sample runs: it rejects exactly the two wrong
ones and keeps all thirteen correct ones. A website the platform *told* us (the ATG
mailto domain) is a fact, not a guess, and bypasses the guard entirely.

---

## Two enrichment upgrades that followed (deep CH match + Places)

The first sample runs matched only ~7 of 19 leads to Companies House, and Invaluable
matched zero — because the shallow, relevance-ranked name search cannot place a *trading*
name (it returned a brass band for "1818 Auctioneers"). Two fixes, both robust-tested:

- **Deep matcher** (`deepmatch.py`) — uses Advanced Search (an unranked substring +
  location filter) on the *distinctive* words of the name, then corroborates each
  candidate against postcode, the resolved domain, SIC code and town. Evidence-weighted
  and fail-closed: a shared postcode alone can't pass, two equally-good candidates refuse
  rather than guess, and a name that's just a number ("1818") can't carry a match.
- **Places fill** (`auctions.enrich.places_fill`) — called only when the platform left a
  gap (Invaluable's missing postcode, LiveAuctioneers' missing website). A maintained
  Google listing beats a web-search guess, and its website still goes through the same
  name-match guard.

Measured on the same 20-lead sample, corporate (= emailable) rate: saleroom 2/5 → **4/5**,
LiveAuctioneers 2/5 → **3/5**, Invaluable 0/5 → **1/5**. Adam Partridge, Acreman, Ashley
Waller and A F Brock all went from unmatched to a confident corporate match.

> Note: decision-maker emails currently read 0 across every run because **all three
> verifiers are out of credit** (MillionVerifier, Reoon free-600, ZeroBounce) — the
> directors are fetched and the permutations generated, but the chain correctly DEFERS
> rather than guessing. Top up any one provider and named emails resume. See
> [[verifier-fallback-chain]].

## Worth running?

| | ATG (saleroom/bidspotter/i-bidder) | LiveAuctioneers | Invaluable |
|---|---|---|---|
| UK houses | ~590 / ~160 / ~240 | ~289 | ~98 (filtered) |
| Postcode in source | ✅ | ✅ | ❌ → Places |
| Own website in source | ✅ (mailto domain) | ❌ → Places | ❌ → Places |
| CH match strength | strong (name + postcode + domain) | strong (+ Places postcode) | now viable (deep match + Places) |

Run the ATG platforms first. LiveAuctioneers is a reasonable second sweep. Invaluable is
last — it is small, heavily overlapping with the others, and its leads cost the most to
resolve per usable contact. Cross-platform duplicates are collapsed by the existing
union-find dedupe on domain and company number, so running all of them is not wasteful,
just diminishing.

**Terms:** both reserve automated access; recorded in each adapter's `terms_note` and
printed into every run log. A record of the decision, not a gate.
