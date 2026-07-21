"""Auction-source configuration — one place for every knob (rate, cache, batch).

Reads from the environment (via the shared outreach .env), with conservative defaults
a solo operator can leave alone. The API keys themselves live in outreach.config
(Companies House, MillionVerifier, Firecrawl, Gemini) — reused, never re-declared.
"""
from __future__ import annotations
import os
import pathlib

from .. import config as _oc   # the pipeline's config: keys + shared settings

# Identify ourselves honestly on every request — no browser spoofing. A site owner can
# see who we are and reach us. (Compliance/politeness is a posture, not a disguise.)
USER_AGENT = os.environ.get(
    "AUCTION_USER_AGENT",
    "SettlePayResearch/0.1 (+https://settlepay.uk; contact hello@settlepay.uk)")

# Politeness controls — deliberately gentle. RAISE only with care.
RATE_LIMIT_SECONDS = float(os.environ.get("AUCTION_RATE_LIMIT_SECONDS", "2.5"))  # min gap between requests
MAX_RETRIES = int(os.environ.get("AUCTION_MAX_RETRIES", "3"))
TIMEOUT_SECONDS = float(os.environ.get("AUCTION_TIMEOUT_SECONDS", "30"))

# Rendered fetches (Firecrawl) are slower and cost a credit each — see
# PoliteClient.get_rendered. Cost is per scraped page on the current plan; it feeds the
# spend ledger, so keep it honest rather than optimistic.
RENDER_TIMEOUT_SECONDS = float(os.environ.get("AUCTION_RENDER_TIMEOUT_SECONDS", "120"))
RENDER_COST_GBP = float(os.environ.get("AUCTION_RENDER_COST_GBP", "0.004"))
# Hard stop on directory paging, so a parser change can never walk a site forever.
MAX_DIRECTORY_PAGES = int(os.environ.get("AUCTION_MAX_DIRECTORY_PAGES", "40"))
# Only UK auctioneers are usable: the PECR gate is Companies House, so a non-UK lead is
# spend with no possible outcome. Set 0 to keep everything a platform lists.
UK_ONLY = os.environ.get("AUCTION_UK_ONLY", "1") not in ("0", "false", "False", "")

# On-disk response cache so re-runs never re-hit the site. Under the scratch/ dir by
# default; override for a durable location.
CACHE_DIR = pathlib.Path(os.environ.get(
    "AUCTION_CACHE_DIR", str(pathlib.Path(_oc.PROJECT_ROOT) / ".auction_cache")))
CACHE_TTL_SECONDS = int(os.environ.get("AUCTION_CACHE_TTL_SECONDS", str(7 * 24 * 3600)))

# Sample-run size (prove end-to-end before scaling).
SAMPLE_SIZE = int(os.environ.get("AUCTION_SAMPLE_SIZE", "25"))

# Output location.
OUTPUT_DIR = pathlib.Path(os.environ.get(
    "AUCTION_OUTPUT_DIR", str(pathlib.Path(_oc.PROJECT_ROOT) / "auction_output")))

# --- scoring weights (Phase 5). Sum need not be 100; the score is normalised. ---
# The explicit manual-payment signal on their own site is the biggest lever — it is
# literal proof of the pain SettlePay removes.
SCORE_WEIGHTS = {
    "manual_payment_signal": 40,   # "pay by bank transfer / cheque / BACS" on their site
    "category_value": 25,          # fine art / antiques / jewellery > general clearance
    "auction_activity": 15,        # has upcoming/next auction, i.e. actively trading
    "decision_maker_email": 20,    # a verified NAMED email was found
}
