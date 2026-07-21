# Recon — Auction Technology Group: the-saleroom.com · bidspotter.co.uk · i-bidder.com

Investigated 2026-07-21. Adapter built: `outreach/auctions/sources/atg.py`.

---

## TL;DR

These are **three brands on one codebase**, so they are **one adapter** parameterised by
base URL — not three. Every URL pattern, page layout and pagination parameter below is
identical across all three; the fixtures in `tests/fixtures/auctions/atg_*.md` come from
the-saleroom and the parser is exercised against all three brands.

They are also the **richest** auction source found so far: the directory listing alone
gives name, full postal address (so postcode **and** country), logo and a live upcoming-
auction count, and the profile page leaks the auctioneer's **own domain** via a `mailto:`.
That last point is worth money — it skips the Firecrawl website *search* the enrichment
stage otherwise pays for and frequently gets wrong.

---

## Access — plain HTTP does not work at all

Every path, `robots.txt` included, is answered by AWS WAF with a browser challenge:

```
$ curl -sI https://www.the-saleroom.com/robots.txt
HTTP/2 202
server: CloudFront
x-amzn-waf-action: challenge
content-length: 0
```

Identical on `bidspotter.co.uk` and `i-bidder.com`. **No robots.txt is served** to a
non-browser client, so there is no crawl directive to read — permitted or otherwise.

Firecrawl (already the pipeline's renderer for JS/blocked sites) fetches all three
normally, so discovery goes through `PoliteClient.get_rendered`, which caches to disk so
re-runs and parser iteration cost no credits.

**Terms:** ATG's site terms reserve automated access. Recorded in each adapter's
`terms_note`, printed into every run log. It is a record, not a gate — running is the
operator's decision, taken 2026-07-21.

---

## Discovery surface

| | |
|---|---|
| Directory | `/en-gb/auctioneers/all` |
| Pagination | `?page=N`, **60 entries a page**; a page with no entries = the end |
| Profile | `/en-gb/auction-catalogues/<slug>` (the slug is the stable source id) |
| Also present | A–Z shards `/en-gb/auctioneers/<letter>`, and `search-filter?Country=…` (not used — the country is already in each listing row, so client-side filtering costs nothing extra) |

Sizes observed: **the-saleroom ≈ 593** auctioneers (10 pages), **BidSpotter ≈ 161**
(3 pages), **i-bidder ≥ 240**. UK density differs sharply and matters for spend:
the-saleroom is **~47% UK** (lots of European houses), BidSpotter and i-bidder are
**~95% UK**. Non-UK houses are dropped before any enrichment spend (`AUCTION_UK_ONLY`),
because the PECR gate is Companies House — a foreign house can never pass it.

BidSpotter and i-bidder overlap heavily with each other (industrial/plant/machinery); the
existing union-find dedupe collapses them on domain and company number.

---

## A directory entry, as rendered

```markdown
## [A & C Auctions of Pendle](https://www.the-saleroom.com/en-gb/auction-catalogues/aandcauctions)

[![A & C Auctions of Pendle](https://cdn.globalauctionplatform.com/…/logo/…png)](…)

Holker MillBurnley RoadColneLancashireBB8 8EGUnited Kingdom

01282 863319

[Add to favourites](…) [View Auctions (0)from A & C Auctions of Pendle](…)
```

| Field | Where from | Note |
|---|---|---|
| Business name | the `##` link text | |
| Slug / source id | the profile URL | stable |
| Postcode | tail of the address run | see the case-sensitivity trap below |
| Country | tail of the address run | the UK filter |
| Upcoming count | `View Auctions (N)` | activity score input |
| Logo | the image link | future branded mock |
| **Telephone** | present | **never read** — no field exists to hold it |

**Parser trap, found and fixed:** the address arrives as one run-together string with no
separators. Matching the postcode case-insensitively lets the outward code swallow the
town's last letter — `…LondonW1W 7LT` became `NW1W 7LT`, a district that does not exist.
The regex is deliberately case-sensitive. Cross-checked against LiveAuctioneers, which
independently reports `W1W 7LT` for the same business. Pinned by a test.

---

## The profile page

Carries the auctioneer's own blurb under a `## <Business Name>` heading, plus `mailto:`
links on their own domain.

- **Categories are read from that blurb only.** The full page carries ATG's site-wide
  category nav (Fine Art, Jewellery, Collectibles…), so reading the whole page would tag
  every auctioneer on the platform identically — exactly the trap Easy Live's
  `og:description` set. No blurb ⇒ **no categories**, rather than wrong ones.
- **Only the mailto's DOMAIN is taken**, to give `own_website`. Which mailbox to actually
  contact stays with the enrichment stage, which owns that policy — profiles often list
  named personal addresses (`steven.parkinson@…`) and those must go through the normal
  named-contact GDPR path, not a shortcut here.

Verified live: `1818 Auctioneers → https://1818auctioneers.co.uk`,
`A & C Auctions of Pendle → https://pendleauctionhouse.co.uk`,
`Anglia Car Auctions Ltd → https://angliacarauctions.co.uk`.

---

## Cost

One rendered page per directory page, plus one per auctioneer profile. A full
the-saleroom sweep ≈ 10 + 593 ≈ 600 credits (~£2.40 at the metered
`AUCTION_RENDER_COST_GBP`); BidSpotter ≈ 165; i-bidder ≈ 245. Metered to the spend ledger
as provider `firecrawl`, and Firecrawl is now in `spend.CASH_PROVIDERS`, so a sweep counts
against `MONTHLY_SPEND_CAP_GBP` instead of arriving as a silent card charge.
