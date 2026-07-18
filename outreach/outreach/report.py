"""Operator daily digest — plain-text summary of the pipeline, mailed once a day.

Rendering REUSES monitor.bounce_stats/breaches (and monitor.db_kill_switch) so
the digest can never disagree with the enforcement path that pauses sending.
Every section renders inside its own guard — a broken query degrades to a loud
'SECTION UNAVAILABLE (<err>)' line, never a silently missing section; a
savepoint per section stops one failed statement aborting the rest of the
transaction. Digests are transactional operator mail: they still go out when
the kill switch is ON (the switch blocks outreach sends, not operator mail).

CLI:  python -m outreach.report        # print today's digest without sending
"""
from __future__ import annotations
import datetime

from . import config, db, monitor

DIGEST_FLAG = "last_daily_digest"


def _section(cur, title: str, render) -> str:
    try:
        cur.execute("savepoint digest_section")
    except Exception:
        pass
    try:
        lines = render()
    except Exception as e:
        try:
            cur.execute("rollback to savepoint digest_section")
        except Exception:
            pass
        lines = [f"SECTION UNAVAILABLE ({e})"]
    return "\n".join([title] + [f"  {line}" for line in lines])


def daily_digest_text(cur) -> str:
    def sent():
        cur.execute(
            "select count(*) filter (where mode='live' and created_at >= now() - interval '24 hours'), "
            "count(*) filter (where mode='live' and created_at >= now() - interval '7 days'), "
            "count(*) filter (where mode='dry_run' and created_at >= now() - interval '24 hours'), "
            "count(*) filter (where mode='dry_run' and created_at >= now() - interval '7 days') "
            "from outreach.sends")
        l24, l7, d24, d7 = cur.fetchone()
        return [f"live: {l24 or 0} (24h) / {l7 or 0} (7d)",
                f"dry-run: {d24 or 0} (24h) / {d7 or 0} (7d)"]

    def inbound():
        cur.execute(
            "select kind, count(*) from outreach.replies "
            "where received_at >= now() - interval '7 days' group by 1")
        by = dict(cur.fetchall())
        return [f"replies: {by.get('reply', 0)}",
                f"bounces: {by.get('bounce', 0)}",
                f"opt-outs: {by.get('unsubscribe', 0)}",
                f"complaints: {by.get('complaint', 0)}"]

    def leads_drafts():
        cur.execute(
            "select count(*) filter (where created_at >= now() - interval '24 hours'), "
            "count(*) filter (where created_at >= now() - interval '7 days') "
            "from outreach.leads")
        new24, new7 = cur.fetchone()
        cur.execute("select count(*) from outreach.drafts where status='awaiting_approval'")
        awaiting = cur.fetchone()[0] or 0
        return [f"new leads: {new24 or 0} (24h) / {new7 or 0} (7d)",
                f"drafts awaiting approval: {awaiting}"]

    def spend_line():
        from . import spend
        total = float(spend.month_total_gbp())
        cap = config.MONTHLY_SPEND_CAP_GBP
        pct = (total / cap * 100) if cap else 0.0
        return [f"month to date: £{total:.2f} of £{cap:.2f} cap ({pct:.0f}%)"]

    def flags():
        found = monitor.breaches(monitor.bounce_stats(cur))
        lines = [f"kill switch (db): {'ON' if monitor.db_kill_switch(cur=cur) else 'off'}"]
        lines += [f"BREACH: {b}" for b in found] or ["no threshold breaches"]
        return lines

    def failed_jobs():
        cur.execute(
            "select count(*) from outreach.jobs where status='failed' "
            "and coalesce(finished_at, created_at) >= now() - interval '24 hours'")
        return [f"failed (24h): {cur.fetchone()[0] or 0}"]

    today = datetime.date.today().isoformat()
    return "\n".join([
        f"SettlePay outreach — daily digest {today}", "",
        _section(cur, "SENT", sent), "",
        _section(cur, "REPLIES / BOUNCES / OPT-OUTS (7d)", inbound), "",
        _section(cur, "NEW LEADS / DRAFTS", leads_drafts), "",
        _section(cur, "SPEND", spend_line), "",
        _section(cur, "FLAGS", flags), "",
        _section(cur, "FAILED JOBS", failed_jobs),
    ]) + "\n"


def send_daily_digest(cur=None) -> dict:
    """Render + mail the digest to the operator, at most once per calendar day
    (ops_flags date throttle). The throttle flag only advances after a
    successful send, so a failed attempt is retried on the next tick."""
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    try:
        today = datetime.date.today().isoformat()
        if monitor.get_flag(DIGEST_FLAG, cur=cur) == today:
            result = {"skipped": "already sent"}
        elif not config.OPERATOR_EMAIL:
            result = {"skipped": "OPERATOR_EMAIL unset"}
        else:
            body = daily_digest_text(cur)
            try:
                from . import gmail
                gmail.send_message(config.GMAIL_SENDER, config.OPERATOR_EMAIL,
                                   f"SettlePay outreach digest — {today}", body)
            except Exception as e:
                result = {"error": str(e)}
            else:
                monitor.set_flag(DIGEST_FLAG, today, reason="daily digest sent",
                                 updated_by="report", cur=cur)
                result = {"sent": config.OPERATOR_EMAIL, "date": today}
        if own:
            conn.commit()
        return result
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    with db.cursor(commit=False) as cur:
        print(daily_digest_text(cur))
