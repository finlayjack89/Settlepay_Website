"""CLI — fetch → enrich → score → dedupe → output. Prove on a small sample first.

    python -m outreach.auctions.run --platform easylive --sample        # 25 leads -> files
    python -m outreach.auctions.run --platform easylive --limit 100     # more
    python -m outreach.auctions.run --platform all --limit 50           # every registered source
    python -m outreach.auctions.run --platform easylive --sample --ingest  # + push to DB drafting

Files land in AUCTION_OUTPUT_DIR (default outreach/auction_output/). The HTTP cache means
a re-run is cheap and idempotent — delete the cache dir to force a refetch.
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

from .. import enrich as _enrich
from ..companies_house import CompaniesHouseClient
from . import brief, config, dedupe, output, score
from .enrich import enrich_lead
from .sources import get_source, platforms

_UA = {"User-Agent": config.USER_AGENT}


def collect(platform: str, *, limit: int, use_cache: bool, ch, resolver, http, provider=None):
    src = get_source(platform)
    src.client.use_cache = use_cache
    if src.terms_note:
        print(f"[{platform}] terms: {src.terms_note}", flush=True)
    out = []
    for i, raw in enumerate(src.iter_auctioneers(limit=limit), 1):
        lead = enrich_lead(raw, http=http, ch=ch, resolver=resolver, provider=provider)
        lead.score, lead.score_breakdown = score.score(lead)
        lead.email_context = brief.build(lead)
        out.append(lead)
        print(f"  {i:>3}. {lead.score:>3}  {lead.business_name[:38]:40} "
              f"{lead.pecr_class:10} {lead.own_website or '(no site)'}", flush=True)
    src.close()
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="outreach.auctions.run")
    p.add_argument("--platform", default="easylive",
                   help="platform key, or 'all' for every registered source")
    p.add_argument("--sample", action="store_true", help=f"cap at {config.SAMPLE_SIZE} leads")
    p.add_argument("--limit", type=int, default=None, help="max leads (overrides --sample)")
    p.add_argument("--no-cache", action="store_true", help="ignore the on-disk HTTP cache")
    p.add_argument("--ingest", action="store_true",
                   help="also push leads into the DB drafting pipeline (writes to prod)")
    p.add_argument("--out", default=None, help="output directory")
    args = p.parse_args(argv)

    limit = args.limit if args.limit is not None else (config.SAMPLE_SIZE if args.sample else None)
    targets = platforms() if args.platform == "all" else [args.platform]
    out_dir = config.OUTPUT_DIR if args.out is None else __import__("pathlib").Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # shared clients. CH cap generous for the batch (search+profile+officers per lead).
    ch = CompaniesHouseClient(max_requests=max(60, (limit or 200) * 4))
    # ELA never exposes the auctioneer's own site, so website discovery is essential —
    # force the Firecrawl resolver regardless of the local WEBSITE_RESOLVER default
    # (which is 'inline' in dev). Falls back to the configured resolver if no key.
    resolver = (_enrich.get_website_resolver("firecrawl")
                if config._oc.FIRECRAWL_API_KEY else _enrich.get_website_resolver())
    http = httpx.Client(timeout=20, follow_redirects=True, headers=_UA)
    t0 = time.monotonic()
    leads = []
    try:
        for platform in targets:
            print(f"\n=== {platform} (limit={limit}) ===", flush=True)
            leads += collect(platform, limit=limit, use_cache=not args.no_cache,
                             ch=ch, resolver=resolver, http=http)
    finally:
        http.close()
        ch.close()

    before = len(leads)
    leads = dedupe.dedupe(leads)
    csv_path, json_path = out_dir / "auction_leads.csv", out_dir / "auction_leads.json"
    output.write_csv(csv_path, leads)
    output.write_json(json_path, leads)

    corporate = sum(1 for ld in leads if ld.pecr_class == "corporate")
    with_dm = sum(1 for ld in leads if ld.decision_maker_email)
    with_pay = sum(1 for ld in leads if ld.payment_methods)
    print(f"\n{before} fetched -> {len(leads)} after dedupe · {corporate} corporate · "
          f"{with_pay} with a payment signal · {with_dm} with a verified named email · "
          f"{time.monotonic()-t0:.0f}s")
    print(f"CSV : {csv_path}\nJSON: {json_path}")

    if args.ingest:
        from .. import db
        with db.cursor() as cur:
            res = ingest_to_pipeline(leads, cur)
        print(f"ingested into pipeline: {res}")
    return 0


def ingest_to_pipeline(leads, cur):
    from . import ingest
    return ingest.to_pipeline(leads, cur=cur)


if __name__ == "__main__":
    sys.exit(main())
