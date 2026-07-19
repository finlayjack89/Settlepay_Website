"""CSV export of the enriched-lead list — the durable, inspectable form of the
reservoir. The SQL tables (outreach.leads + enrichment) ARE the list; this makes
it portable (open in a spreadsheet, hand to a tool, keep a snapshot). Read-only.
"""
from __future__ import annotations
import csv
import io
from typing import Optional

from . import config, db

_COLUMNS = [
    "company_number", "company_name", "state", "sic", "website", "contact_email",
    "contact_tier", "size_band", "icp_fit", "already_takes_card", "signal_source",
    "signal", "updated_at",
]

_SQL = """
select l.company_number, l.company_name, l.state::text, l.sic_codes[1],
       e.website, e.contact_email, e.contact_tier,
       e.scraped->>'size_band', e.scraped->>'icp_fit', e.scraped->>'already_takes_card',
       e.scraped->>'signal_source', e.signal, l.updated_at
from outreach.leads l
left join outreach.enrichment e on e.company_number = l.company_number
{where}
order by l.updated_at desc
"""


def leads_csv(*, state: Optional[str] = None, cur=None) -> str:
    """Return the lead list as CSV text. `state` filters (e.g. 'enriched' = the
    ready pool); None exports every lead. Uses the caller's cursor if given."""
    where, params = "", ()
    if state:
        where, params = "where l.state = %s", (state,)
    sql = _SQL.format(where=where)

    def _run(c) -> list[tuple]:
        c.execute(sql, params)
        return c.fetchall()

    if cur is not None:
        rows = _run(cur)
    else:
        with db.cursor(commit=False) as c:
            rows = _run(c)

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(_COLUMNS)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return buf.getvalue()


def write_csv(path: str, *, state: Optional[str] = None) -> int:
    """Write the CSV to `path`; return the row count (excluding header)."""
    text = leads_csv(state=state)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    return max(0, text.count("\n") - 1)
