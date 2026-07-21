"""The auction pipeline: fetch → enrich → score → dedupe → output (→ optional ingest).

`run_pipeline` is the one entry point, used by BOTH the CLI here and the console's
`auction_run` job — so the dashboard button and the terminal do exactly the same thing.
Progress goes through a `log` callback, which the job wires to its own live job log.

    python -m outreach.auctions.run --platform easylive --sample        # 25 -> files
    python -m outreach.auctions.run --platform easylive --limit 100
    python -m outreach.auctions.run --platform all --limit 50
    python -m outreach.auctions.run --platform easylive --sample --ingest   # + into the pipeline

Files land in AUCTION_OUTPUT_DIR. The on-disk HTTP cache makes a re-run cheap and
idempotent — delete the cache dir to force a refetch.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from typing import Callable, Optional

import httpx

from .. import enrich as _enrich
from ..companies_house import CompaniesHouseClient
from . import brief, config, dedupe, output, score
from .enrich import enrich_lead
from .sources import get_source, platforms

_UA = {"User-Agent": config.USER_AGENT}


def collect(platform: str, *, limit: Optional[int], use_cache: bool, ch, resolver, http,
            provider=None, log: Callable[[str], None] = print):
    src = get_source(platform)
    src.client.use_cache = use_cache
    if src.terms_note:
        log(f"[{platform}] terms: {src.terms_note}")
    out = []
    for i, raw in enumerate(src.iter_auctioneers(limit=limit), 1):
        lead = enrich_lead(raw, http=http, ch=ch, resolver=resolver, provider=provider)
        lead.score, lead.score_breakdown = score.score(lead)
        lead.email_context = brief.build(lead)
        out.append(lead)
        log(f"{i:>3}. [{lead.score:>3}] {lead.business_name[:38]} — {lead.pecr_class}"
            + (f" — {lead.decision_maker_email}" if lead.decision_maker_email else "")
            + (f" — {lead.own_website}" if lead.own_website else " — no site"))
    src.close()
    return out


def run_pipeline(platform: str = "easylive", *, limit: Optional[int] = None,
                 use_cache: bool = True, ingest: bool = False,
                 out_dir: Optional[pathlib.Path] = None,
                 log: Callable[[str], None] = print) -> dict:
    """Run the full auction pipeline for one platform (or 'all'). Returns a summary dict
    and always writes the CSV/JSON. `ingest` additionally lands the leads in the outreach
    pipeline so the existing draft → review → send chain picks them up."""
    targets = platforms() if platform == "all" else [platform]
    out_dir = out_dir or config.OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # shared clients. CH cap generous for the batch (search + profile + officers per lead).
    ch = CompaniesHouseClient(max_requests=max(60, (limit or 200) * 4))
    # the platform never exposes the auctioneer's own site, so website discovery is
    # essential — force Firecrawl regardless of the local WEBSITE_RESOLVER default.
    resolver = (_enrich.get_website_resolver("firecrawl")
                if config._oc.FIRECRAWL_API_KEY else _enrich.get_website_resolver())
    http = httpx.Client(timeout=20, follow_redirects=True, headers=_UA)
    t0 = time.monotonic()
    leads: list = []
    try:
        for p in targets:
            log(f"=== {p} (limit={limit or 'all'}) ===")
            leads += collect(p, limit=limit, use_cache=use_cache, ch=ch,
                             resolver=resolver, http=http, log=log)
    finally:
        http.close()
        ch.close()

    before = len(leads)
    leads = dedupe.dedupe(leads)
    csv_path, json_path = out_dir / "auction_leads.csv", out_dir / "auction_leads.json"
    output.write_csv(csv_path, leads)
    output.write_json(json_path, leads)

    summary = {
        "platform": platform,
        "fetched": before,
        "leads": len(leads),
        "corporate": sum(1 for ld in leads if ld.pecr_class == "corporate"),
        "with_payment_signal": sum(1 for ld in leads if ld.payment_methods),
        "with_decision_maker_email": sum(1 for ld in leads if ld.decision_maker_email),
        "seconds": round(time.monotonic() - t0),
        "csv": str(csv_path), "json": str(json_path),
    }
    log(f"{before} fetched -> {len(leads)} after dedupe · {summary['corporate']} corporate · "
        f"{summary['with_payment_signal']} with a payment signal · "
        f"{summary['with_decision_maker_email']} with a verified named email · "
        f"{summary['seconds']}s")

    if ingest:
        from .. import db
        from . import ingest as ingest_mod
        with db.cursor() as cur:
            summary["ingested"] = ingest_mod.to_pipeline(leads, cur=cur)
        log(f"into the lead pipeline: {summary['ingested']}")
    return summary


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
    summary = run_pipeline(args.platform, limit=limit, use_cache=not args.no_cache,
                           ingest=args.ingest,
                           out_dir=pathlib.Path(args.out) if args.out else None)
    print(f"CSV : {summary['csv']}\nJSON: {summary['json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
