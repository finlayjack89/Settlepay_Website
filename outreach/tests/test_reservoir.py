"""Demand-pull reservoir status + CSV export of the lead list."""
import uuid

import pytest

from outreach import export, stats

pytestmark = pytest.mark.floor_h


def _lead(cur, cn, name, state):
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state, sic_codes) values (%s,%s,'ltd','corporate',%s,%s)",
                (cn, name, state, ["96020"]))


def test_reservoir_status_counts_ready_and_backlog(db_rollback):
    cur = db_rollback.cursor()
    tag = uuid.uuid4().hex[:6]
    _lead(cur, f"R1_{tag}", "Ready One", "enriched")
    _lead(cur, f"R2_{tag}", "Ready Two", "enriched")
    _lead(cur, f"B1_{tag}", "Backlog One", "discovered")
    s = stats.reservoir_status(cur, target=150)
    assert s["ready"] >= 2 and s["backlog"] >= 1
    assert s["deficit"] == max(0, 150 - s["ready"])


def test_reservoir_full_gives_zero_deficit(db_rollback):
    cur = db_rollback.cursor()
    cur.execute("select count(*) from outreach.leads where state='enriched'")
    ready = cur.fetchone()[0]
    s = stats.reservoir_status(cur, target=0)   # target below ready => full
    assert s["deficit"] == 0 and s["ready"] == ready


def test_leads_csv_header_and_row(db_rollback):
    cur = db_rollback.cursor()
    cn = f"CSV_{uuid.uuid4().hex[:8]}"
    _lead(cur, cn, "Export Me Ltd", "enriched")
    cur.execute("insert into outreach.enrichment (company_number, website, contact_email, "
                "contact_tier, signal, scraped) values (%s,'https://x.co','info@x.co','verified',"
                "'a signal', '{\"size_band\":\"micro\",\"icp_fit\":true}'::jsonb)", (cn,))
    csv_text = export.leads_csv(state="enriched", cur=cur)
    lines = csv_text.splitlines()
    assert lines[0].startswith("company_number,company_name,state")
    row = next(l for l in lines if cn in l)
    assert "Export Me Ltd" in row and "info@x.co" in row and "micro" in row
