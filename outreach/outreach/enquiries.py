"""Inbound enquiries reader — reads/updates public.<ENQUIRY_SOURCE_TABLE> (website
form submissions). The inbound half of the unified operations console.

Shares the outreach DB connection (config.DATABASE_URL); `public` is already on the
search_path. Ported from the standalone console/db.py so the two consoles become one.
Functions take a dict-row cursor (see db.dict_cursor) — the caller manages the
connection, mirroring the outreach stats/review modules.
"""
from __future__ import annotations

from . import config

_ALLOWED_TABLES = {"leads", "enquiries"}
STATUSES = ("new", "contacted", "quoted", "won", "lost", "client")


def _table() -> str:
    t = config.ENQUIRY_SOURCE_TABLE
    if t not in _ALLOWED_TABLES:
        raise ValueError(f"ENQUIRY_SOURCE_TABLE must be one of {_ALLOWED_TABLES}")
    return f"public.{t}"


def overview(cur) -> dict:
    cur.execute(f"""
        select
          count(*)                                                        as total,
          count(*) filter (where status='new')                           as new,
          count(*) filter (where status='contacted')                     as contacted,
          count(*) filter (where status='quoted')                        as quoted,
          count(*) filter (where status='won')                           as won,
          count(*) filter (where status='client')                        as client,
          count(*) filter (where status='lost')                          as lost,
          count(*) filter (where created_at > now() - interval '7 days') as this_week
        from {_table()}
    """)
    return cur.fetchone()


def status_counts(cur) -> dict:
    cur.execute(f"select status, count(*) as n from {_table()} group by status")
    return {r["status"]: r["n"] for r in cur.fetchall()}


def recent(cur, limit: int = 8) -> list[dict]:
    cur.execute(
        f"select id, business, name, email, status, created_at from {_table()} "
        f"order by created_at desc limit %s", (limit,))
    return cur.fetchall()


def list_enquiries(cur, status: str = "") -> list[dict]:
    if status:
        cur.execute(
            f"select id, business, name, email, status, created_at from {_table()} "
            f"where status = %s order by created_at desc limit 500", (status,))
    else:
        cur.execute(
            f"select id, business, name, email, status, created_at from {_table()} "
            f"order by created_at desc limit 500")
    return cur.fetchall()


def get(cur, lead_id: str) -> dict | None:
    cur.execute(
        f"select id, business, name, email, message, source, status, notes, "
        f"created_at, updated_at from {_table()} where id = %s::uuid", (lead_id,))
    return cur.fetchone()


def update(cur, lead_id: str, status: str, notes: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    cur.execute(
        f"update {_table()} set status = %s, notes = %s where id = %s::uuid",
        (status, notes or None, lead_id))


# --- bookings (consultations captured from Cal.com via the cal-webhook function) ---

def bookings_exists(cur) -> bool:
    """True once the public.bookings migration has been applied."""
    cur.execute("select to_regclass('public.bookings') is not null as ok")
    row = cur.fetchone()
    return bool(row and row["ok"])


def upcoming_bookings(cur, limit: int = 100) -> list[dict]:
    cur.execute(
        "select id, status, title, start_at, end_at, attendee_name, attendee_email, "
        "attendee_timezone, join_url, lead_id from public.bookings "
        "where status <> 'cancelled' and start_at >= now() - interval '1 hour' "
        "order by start_at asc limit %s", (limit,))
    return cur.fetchall()


def recent_bookings(cur, limit: int = 25) -> list[dict]:
    cur.execute(
        "select id, status, title, start_at, attendee_name, attendee_email, join_url, lead_id "
        "from public.bookings "
        "where status = 'cancelled' or start_at < now() - interval '1 hour' "
        "order by start_at desc limit %s", (limit,))
    return cur.fetchall()
