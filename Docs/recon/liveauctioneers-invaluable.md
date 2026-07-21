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

## Worth running?

| | ATG (saleroom/bidspotter/i-bidder) | LiveAuctioneers | Invaluable |
|---|---|---|---|
| UK houses | ~590 / ~160 / ~240 | ~289 | ~98 (filtered) |
| Postcode in source | ✅ | ✅ | ❌ |
| Own website in source | ✅ (mailto domain) | ❌ | ❌ |
| CH match strength | strong (name + postcode) | strong | weak (name only) |

Run the ATG platforms first. LiveAuctioneers is a reasonable second sweep. Invaluable is
last — it is small, heavily overlapping with the others, and its leads cost the most to
resolve per usable contact. Cross-platform duplicates are collapsed by the existing
union-find dedupe on domain and company number, so running all of them is not wasteful,
just diminishing.

**Terms:** both reserve automated access; recorded in each adapter's `terms_note` and
printed into every run log. A record of the decision, not a gate.
