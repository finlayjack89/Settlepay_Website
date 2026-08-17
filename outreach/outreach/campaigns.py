"""Named, aimed slices of the discovery grid.

The grid is roughly 14,700 vertical × town queries swept by ONE cursor, and the credit
runs out long before the grid does. That makes the cursor's position — not anyone's
intention — the thing that decides what gets discovered. It is how auctioneers, the one
vertical with a real client, ended up about seven months away at the observed sweep rate:
nobody de-prioritised them; they were unreachable by construction.

A campaign is the fix. It names a slice ("auctioneers", "Yorkshire"), gives that slice its
own cursor and its own target, and counts what it actually produced. The scheduled sweep
keeps its own cursor and carries on regardless, so aiming a run at something never costs
you the background coverage.

Two deliberate choices:

- **The slice is stored as the operator's words**, not as an expanded list of queries. The
  grid gains verticals over time; a campaign should follow it rather than freeze a copy
  that quietly stops matching.
- **`found` is a COUNT, not a tally.** Leads carry `campaign_id`, so progress is a query
  against reality. A counter incremented per run drifts the moment anything is retried,
  rolled back, or discarded downstream — and a progress bar that lies is worse than none.
"""
from __future__ import annotations
from typing import Optional

from . import audit, db, targeting

ACTIVE, PAUSED, DONE = "active", "paused", "done"


def cursor_key(name: str) -> str:
    """Namespaced so a campaign cursor can never collide with the global sweep's."""
    slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.lower())[:40]
    return f"places_grid_cursor:campaign:{slug}"


def create(*, name: str, vertical: str = "all", region: str = "all", target: int = 100,
           by: str = "operator", cur=None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("a campaign needs a name")
    if target <= 0:
        raise ValueError("a campaign needs a target above zero")
    # Validate the slice NOW, so a typo surfaces here rather than as a campaign that
    # sweeps the entire grid under a name that says otherwise.
    if vertical not in ("all",) and vertical not in targeting.PLACES_VERTICAL_GROUPS:
        raise ValueError(f"unknown vertical: {vertical}")
    if region not in ("all",) and region.title() not in targeting.PLACES_REGIONS:
        raise ValueError(f"unknown region: {region}")

    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute(
            "insert into outreach.campaigns "
            "(name, vertical, region, target, cursor_key, created_by) "
            "values (%s,%s,%s,%s,%s,%s) returning id",
            (name, vertical, region, target, cursor_key(name), by))
        camp_id = cur.fetchone()[0]
        audit.record(None, "campaign_created", source="campaigns",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"{name}: {vertical} / {region}, target {target}, by {by}",
                     detail={"campaign_id": camp_id, "vertical": vertical,
                             "region": region, "target": target}, cur=cur)
        if own:
            conn.commit()
        return {"id": camp_id, "name": name, "vertical": vertical, "region": region,
                "target": target, "cursor_key": cursor_key(name)}
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def get(campaign_id: int, *, cur=None) -> Optional[dict]:
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute(
            "select id, name, vertical, region, target, status, cursor_key "
            "from outreach.campaigns where id = %s", (campaign_id,))
        row = cur.fetchone()
        if not row:
            return None
        keys = ("id", "name", "vertical", "region", "target", "status", "cursor_key")
        return dict(zip(keys, row))
    finally:
        if own and conn is not None:
            conn.close()


def progress(cur, campaign_id: int) -> int:
    """How many corporate leads this campaign actually produced.

    Counted, not tallied — and counted on `subscriber_class` rather than on rows inserted,
    because a Places result is not yet a lead we may write to. A campaign that discovered
    500 sole traders has found nothing.
    """
    cur.execute("select count(*) from outreach.leads "
                "where campaign_id = %s and subscriber_class = 'corporate'",
                (campaign_id,))
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def listing(cur) -> list[dict]:
    cur.execute(
        "select c.id, c.name, c.vertical, c.region, c.target, c.status, c.created_at, "
        "  (select count(*) from outreach.leads l "
        "    where l.campaign_id = c.id and l.subscriber_class = 'corporate'), "
        "  (select count(*) from outreach.leads l where l.campaign_id = c.id) "
        "from outreach.campaigns c order by "
        "  case c.status when 'active' then 0 when 'paused' then 1 else 2 end, c.id desc")
    out = []
    for cid, name, vert, region, target, status, created, found, seen in cur.fetchall():
        out.append({"id": cid, "name": name, "vertical": vert, "region": region,
                    "target": target, "status": status, "created_at": created,
                    "found": found or 0, "discovered": seen or 0,
                    "pct": min(100, round(100 * (found or 0) / max(target, 1)))})
    return out


def set_status(campaign_id: int, status: str, *, by: str = "operator", cur=None) -> None:
    if status not in (ACTIVE, PAUSED, DONE):
        raise ValueError(f"unknown status: {status}")
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute("update outreach.campaigns set status=%s, updated_at=now() "
                    "where id=%s", (status, campaign_id))
        audit.record(None, "campaign_status", source="campaigns",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"campaign {campaign_id} -> {status} by {by}",
                     detail={"campaign_id": campaign_id, "status": status}, cur=cur)
        if own:
            conn.commit()
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def tag(cur, campaign_id: int, company_numbers: list[str]) -> int:
    """Attribute the leads a campaign's own pass created, by id.

    By id rather than by "everything since a timestamp", because Postgres freezes `now()`
    at transaction start: every lead a tick inserts shares one `created_at`, so no time
    comparison can separate this run's rows from the ones already there. discover_to_leads
    returns exactly what it created; that list is the only honest answer.

    Already-attributed leads are left alone — a lead belongs to whichever campaign found
    it first — and the scheduled sweep's leads stay unattributed, because that is what
    they are.
    """
    if not company_numbers:
        return 0
    cur.execute(
        "update outreach.leads set campaign_id = %s "
        "where campaign_id is null and company_number = any(%s)",
        (campaign_id, list(company_numbers)))
    return cur.rowcount or 0
