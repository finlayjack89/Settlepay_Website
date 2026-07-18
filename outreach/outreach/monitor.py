"""Deliverability monitor — bounce/complaint rates, DB kill switch, auto-pause.

Owns threshold ENFORCEMENT: `bounce_stats` + `breaches` are the single source of
truth that report.py reuses, so the operator digest can never disagree with what
actually pauses sending. Thresholds come from sequence.graduation_thresholds()
(sequence_config.json), never hardcoded here.

The DB kill switch (ops_flags key 'kill_switch') is an ADDITION to env
KILL_SWITCH, which remains the hard override; reads FAIL OPEN (any DB error ->
False) so a DB outage can never mask the env switch path. Auto-pause is one-way:
the monitor only ever turns the switch ON — clearing it is a human decision.

CLI:  python -m outreach.monitor       # compute stats, pause + alert on breach
"""
from __future__ import annotations

from . import audit, config, db, sequence
from .stats import sic_label

# rates over fewer live sends than this are noise, not signal
MIN_SENT_FOR_RATES = 20
_TRUTHY = {"1", "true", "yes", "on"}


# --------------------------------------------------------------------------- #
#  ops_flags (DB-backed operational overrides)
# --------------------------------------------------------------------------- #
def get_flag(key: str, *, cur=None):
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute("select value from outreach.ops_flags where key=%s", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        if own and conn is not None:
            conn.close()


def set_flag(key: str, value: str, *, reason: str = "", updated_by: str = "system",
             cur=None) -> None:
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        cur.execute(
            "insert into outreach.ops_flags (key, value, reason, updated_by, updated_at) "
            "values (%s,%s,%s,%s,now()) "
            "on conflict (key) do update set value=excluded.value, reason=excluded.reason, "
            "updated_by=excluded.updated_by, updated_at=now()",
            (key, value, reason, updated_by))
        if own:
            conn.commit()
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


def db_kill_switch(cur=None) -> bool:
    """DB-backed kill switch read. FAIL-OPEN: any failure reads as False, because
    env KILL_SWITCH stays the hard override and a DB outage must never be able
    to mask that path by pretending the switch is on."""
    try:
        value = get_flag("kill_switch", cur=cur)
    except Exception:
        return False
    return value is not None and str(value).strip().lower() in _TRUTHY


def set_kill_switch(on: bool, *, reason: str = "", updated_by: str = "system",
                    cur=None) -> None:
    set_flag("kill_switch", "1" if on else "0", reason=reason,
             updated_by=updated_by, cur=cur)


# --------------------------------------------------------------------------- #
#  deliverability stats + threshold breaches
# --------------------------------------------------------------------------- #
def _shape(sent: int, bounced: int, complaints: int) -> dict:
    return {"sent": sent, "bounced": bounced, "complaints": complaints,
            "bounce_rate": (bounced / sent) if sent else 0.0,
            "complaint_rate": (complaints / sent) if sent else 0.0}


def bounce_stats(cur, *, window_days: int = 14) -> dict:
    """Live-send deliverability over the window: global + per-vertical
    (leads.sic_codes[1]) sent/bounced/complaint counts and rates. A bounce is a
    lead that transitioned to state 'bounced' in the window OR a replies row of
    kind 'bounce' (deduplicated per company; an unattributable bounce reply
    still counts — it is still a bounce of one of our sends)."""
    cur.execute(
        "select count(*) from outreach.sends "
        "where mode='live' and created_at >= now() - make_interval(days => %s)",
        (window_days,))
    sent = cur.fetchone()[0] or 0

    cur.execute(
        "select count(distinct key) from ("
        "  select company_number as key from outreach.leads "
        "   where state='bounced' and updated_at >= now() - make_interval(days => %s)"
        "  union all "
        "  select coalesce(company_number, 'reply:' || id::text) from outreach.replies "
        "   where kind='bounce' and received_at >= now() - make_interval(days => %s)"
        ") b", (window_days, window_days))
    bounced = cur.fetchone()[0] or 0

    cur.execute(
        "select count(*) from outreach.replies "
        "where kind='complaint' and received_at >= now() - make_interval(days => %s)",
        (window_days,))
    complaints = cur.fetchone()[0] or 0

    counts: dict[str, dict] = {}

    def bucket(sic: str) -> dict:
        return counts.setdefault(sic, {"sent": 0, "bounced": 0, "complaints": 0})

    cur.execute(
        "select coalesce(l.sic_codes[1], '?'), count(*) "
        "from outreach.sends s "
        "left join outreach.leads l on l.company_number = s.company_number "
        "where s.mode='live' and s.created_at >= now() - make_interval(days => %s) "
        "group by 1", (window_days,))
    for sic, n in cur.fetchall():
        bucket(sic)["sent"] = n or 0

    cur.execute(
        "select coalesce(l.sic_codes[1], '?'), count(distinct l.company_number) "
        "from outreach.leads l "
        "where (l.state='bounced' and l.updated_at >= now() - make_interval(days => %s)) "
        "   or exists (select 1 from outreach.replies r "
        "              where r.company_number = l.company_number and r.kind='bounce' "
        "                and r.received_at >= now() - make_interval(days => %s)) "
        "group by 1", (window_days, window_days))
    for sic, n in cur.fetchall():
        bucket(sic)["bounced"] = n or 0

    cur.execute(
        "select coalesce(l.sic_codes[1], '?'), count(*) "
        "from outreach.replies r "
        "join outreach.leads l on l.company_number = r.company_number "
        "where r.kind='complaint' and r.received_at >= now() - make_interval(days => %s) "
        "group by 1", (window_days,))
    for sic, n in cur.fetchall():
        bucket(sic)["complaints"] = n or 0

    verticals = {}
    for sic, c in counts.items():
        v = _shape(c["sent"], c["bounced"], c["complaints"])
        v["label"] = sic_label(sic if sic != "?" else None)
        verticals[sic] = v

    stats = _shape(sent, bounced, complaints)
    stats["window_days"] = window_days
    stats["verticals"] = verticals
    return stats


def breaches(stats: dict) -> list[str]:
    """Human-readable threshold breaches (global + per-vertical). Rates only
    count once the denominator is meaningful (MIN_SENT_FOR_RATES live sends)."""
    th = sequence.graduation_thresholds()
    max_bounce = th.get("max_bounce_rate", 0.02)
    max_complaint = th.get("max_complaint_rate", 0.001)
    window = stats.get("window_days", 14)
    out: list[str] = []

    def check(scope: str, s: dict) -> None:
        if s.get("sent", 0) < MIN_SENT_FOR_RATES:
            return
        if s["bounce_rate"] > max_bounce:
            out.append(
                f"{scope} bounce rate {s['bounce_rate']:.2%} exceeds {max_bounce:.2%} "
                f"({s['bounced']}/{s['sent']} live sends, {window}d)")
        if s["complaint_rate"] > max_complaint:
            out.append(
                f"{scope} complaint rate {s['complaint_rate']:.3%} exceeds {max_complaint:.3%} "
                f"({s['complaints']}/{s['sent']} live sends, {window}d)")

    check("global", stats)
    for sic, s in (stats.get("verticals") or {}).items():
        check(f"vertical {s.get('label', sic)} [{sic}]", s)
    return out


# --------------------------------------------------------------------------- #
#  auto-pause (the tick's deliverability guard)
# --------------------------------------------------------------------------- #
def _alert_operator(found: list[str]) -> None:
    """Best-effort operator alert — transactional mail, exempt from the kill
    switch. Wrapped so an alerting failure (gmail unconfigured, network) can
    never crash the tick; the pause itself has already been recorded."""
    if not config.OPERATOR_EMAIL:
        return
    try:
        from . import gmail
        body = ("Outreach auto-paused: the DB kill switch is now ON.\n\n"
                "Deliverability breaches:\n"
                + "\n".join(f"- {b}" for b in found)
                + "\n\nSending stays blocked until the switch is cleared by a human.")
        gmail.send_message(config.GMAIL_SENDER, config.OPERATOR_EMAIL,
                           "Outreach paused: deliverability threshold breached", body)
    except Exception:
        pass


def check_and_pause(cur=None) -> dict:
    """Compute deliverability stats; on any threshold breach flip the DB kill
    switch ON and alert the operator. The alert only fires on the off->on
    transition so a persistent breach doesn't re-email every tick."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        stats = bounce_stats(cur)
        found = breaches(stats)
        if found:
            already = db_kill_switch(cur=cur)
            reason = "; ".join(found)
            set_kill_switch(True, reason=reason, updated_by="monitor", cur=cur)
            audit.record(None, "auto_pause", source="monitor", reason=reason, cur=cur)
            if not already:
                _alert_operator(found)
        if own:
            conn.commit()
        return {"stats": stats, "breaches": found, "paused": bool(found)}
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    print(check_and_pause())
