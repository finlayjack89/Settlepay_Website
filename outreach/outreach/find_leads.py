"""Phase B — find_leads: discover active companies via Companies House Advanced
Search, dedupe on company_number, and write them to outreach.leads (discovered).

Classification/suppression happens in phase C (the PECR firewall); discovery only
records the company facts (incl. company_type) so C can classify without re-fetching.
No contact happens at this stage.
"""
from __future__ import annotations
import json
import sys

from . import audit, db, targeting
from .companies_house import CompaniesHouseClient

SIC_ESTATE_AGENTS = "68310"


def run(*, target: int = 50, sic_codes: str | None = None, name_includes: str | None = None,
        incorporated_from: str | None = None, incorporated_to: str | None = None,
        exclude_shells: bool = True, skip_dormant: bool = False,
        client=None, dry_run: bool = False) -> dict:
    """Discover active companies via Companies House Advanced Search and write the
    survivors to outreach.leads (discovered). Targeting filters (free, applied before
    any paid discovery downstream):
      - default SIC sweep = the SettlePay ICP verticals (targeting.TARGET_SICS)
      - `name_includes` for name-based discovery (e.g. "auction" — no clean SIC)
      - `incorporated_from` (YYYY-MM-DD) to require a trading age
      - `exclude_shells` drops SPV/holding/nominee-named companies
      - `skip_dormant` (off by default; costs 1 extra CH call/company) drops
        companies whose last accounts are dormant/none
    """
    if not sic_codes and not name_includes:
        sic_codes = ",".join(targeting.TARGET_SICS)   # default = the ICP sweep
    owns_client = client is None
    client = client or CompaniesHouseClient()
    seen: set[str] = set()
    rows: list[dict] = []
    excluded_shells = 0
    dormant = 0
    try:
        for it in client.iter_companies(
            sic_codes=sic_codes, company_status="active", target=target,
            incorporated_from=incorporated_from, incorporated_to=incorporated_to,
            company_name_includes=name_includes,
        ):
            num = it.get("company_number")
            name = it.get("company_name")
            if not num or not name or num in seen:
                continue  # dedupe + require valid key fields
            seen.add(num)
            if exclude_shells and targeting.is_excluded_name(name):
                excluded_shells += 1
                continue
            if skip_dormant:
                try:
                    prof = client.get_profile(num)
                    if targeting.is_dormant(((prof.get("accounts") or {}).get("last_accounts") or {}).get("type")):
                        dormant += 1
                        continue
                except Exception:
                    pass  # never let a profile fetch failure drop a real lead
            rows.append(it)

        if dry_run:
            return {"would_insert": len(rows), "excluded_shells": excluded_shells,
                    "dormant_skipped": dormant, "dry_run": True}

        inserted = 0
        source_desc = f"SIC {sic_codes}" if sic_codes else f"name~{name_includes!r}"
        with db.cursor() as cur:
            for it in rows:
                cur.execute(
                    "insert into outreach.leads "
                    "(company_number, company_name, company_status, company_type, "
                    " sic_codes, registered_address, state, source) "
                    "values (%s,%s,%s,%s,%s,%s,'discovered',%s) "
                    "on conflict (company_number) do nothing",
                    (it.get("company_number"), it.get("company_name"),
                     it.get("company_status"), it.get("company_type"),
                     it.get("sic_codes"),
                     json.dumps(it.get("registered_office_address")),
                     "companies_house_advanced_search"),
                )
                if cur.rowcount:
                    inserted += 1
                    audit.record(
                        it.get("company_number"), "discovered",
                        source="companies_house_advanced_search",
                        lawful_basis=audit.LEGITIMATE_INTERESTS,
                        reason=f"{source_desc} active company", cur=cur,
                    )
        return {"inserted": inserted, "fetched": len(rows),
                "excluded_shells": excluded_shells, "dormant_skipped": dormant}
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    print(run(target=n))
