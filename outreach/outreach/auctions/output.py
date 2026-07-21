"""Output (Phase 6) — write the enriched, scored lead list as CSV and JSON.

CSV for a spreadsheet (lists flattened to '; '-joined strings); JSON for a tool or the
drafting hand-off (structure preserved). Both carry the same fields and the same order,
highest score first.
"""
from __future__ import annotations

import csv
import dataclasses
import json

from .models import EnrichedLead

# column order for the CSV — the operator-legible fields first, provenance last
COLUMNS = [
    "score", "business_name", "pecr_class", "platform", "own_website", "domain",
    "payment_methods", "payment_quote", "categories", "next_auction_date", "upcoming_count",
    "company_number", "company_status", "company_type", "directors",
    "decision_maker_name", "decision_maker_email", "decision_maker_confidence",
    "generic_email", "generic_confidence", "icp_fit", "signal",
    "location", "postcode", "listing_url", "logo_url", "email_context",
    "score_breakdown", "notes",
]


def write_csv(path, leads: list[EnrichedLead]) -> int:
    rows = [ld.as_row() for ld in leads]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in COLUMNS})
    return len(rows)


def write_json(path, leads: list[EnrichedLead]) -> int:
    data = [dataclasses.asdict(ld) for ld in leads]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return len(data)
