"""Phase B — find_leads: discover active companies via Companies House Advanced
Search, dedupe on company_number, and write them to outreach.leads (discovered).

Classification/suppression happens in phase C (the PECR firewall); discovery only
records the company facts (incl. company_type) so C can classify without re-fetching.
No contact happens at this stage.
"""
from __future__ import annotations
import json
import sys

from . import audit, db
from .companies_house import CompaniesHouseClient

SIC_ESTATE_AGENTS = "68310"


def run(*, target: int = 50, sic_codes: str = SIC_ESTATE_AGENTS, client=None,
        dry_run: bool = False) -> dict:
    owns_client = client is None
    client = client or CompaniesHouseClient()
    seen: set[str] = set()
    rows: list[dict] = []
    try:
        for it in client.iter_companies(sic_codes=sic_codes, company_status="active", target=target):
            num = it.get("company_number")
            if not num or not it.get("company_name") or num in seen:
                continue  # dedupe + require valid key fields
            seen.add(num)
            rows.append(it)

        if dry_run:
            return {"would_insert": len(rows), "dry_run": True}

        inserted = 0
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
                        reason=f"SIC {sic_codes} active company", cur=cur,
                    )
        return {"inserted": inserted, "fetched": len(rows)}
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    print(run(target=n))
