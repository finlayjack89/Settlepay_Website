"""Postgres access for the operations console — reads/updates public.leads
(website enquiries). Connection string (Supabase session pooler) comes from
DATABASE_URL in console/.env. Secrets never live in the repo.
"""
from __future__ import annotations
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# 'leads' now; becomes 'enquiries' after the planned public.leads → public.enquiries
# rename — keep in step with the outreach pipeline's ENQUIRY_SOURCE_TABLE.
SOURCE_TABLE = os.environ.get("ENQUIRY_SOURCE_TABLE", "leads").strip()
_ALLOWED_TABLES = {"leads", "enquiries"}
if SOURCE_TABLE not in _ALLOWED_TABLES:
    raise ValueError(f"ENQUIRY_SOURCE_TABLE must be one of {_ALLOWED_TABLES}")
_T = f"public.{SOURCE_TABLE}"

STATUSES = ("new", "contacted", "quoted", "won", "lost", "client")


def db_ok() -> bool:
    return bool(DATABASE_URL)


@contextmanager
def cursor():
    conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    finally:
        conn.close()


def overview(cur) -> dict:
    cur.execute(f"""
        select
          count(*)                                                         as total,
          count(*) filter (where status='new')                            as new,
          count(*) filter (where status='contacted')                      as contacted,
          count(*) filter (where status='quoted')                         as quoted,
          count(*) filter (where status='won')                            as won,
          count(*) filter (where status='client')                         as client,
          count(*) filter (where status='lost')                           as lost,
          count(*) filter (where created_at > now() - interval '7 days')  as this_week
        from {_T}
    """)
    return cur.fetchone()


def status_counts(cur) -> dict:
    cur.execute(f"select status, count(*) as n from {_T} group by status")
    return {r["status"]: r["n"] for r in cur.fetchall()}


def recent(cur, limit: int = 8) -> list[dict]:
    cur.execute(
        f"select id, business, name, email, status, created_at from {_T} "
        f"order by created_at desc limit %s", (limit,))
    return cur.fetchall()


def list_enquiries(cur, status: str = "") -> list[dict]:
    if status:
        cur.execute(
            f"select id, business, name, email, status, created_at from {_T} "
            f"where status = %s order by created_at desc limit 500", (status,))
    else:
        cur.execute(
            f"select id, business, name, email, status, created_at from {_T} "
            f"order by created_at desc limit 500")
    return cur.fetchall()


def get(cur, lead_id: str) -> dict | None:
    cur.execute(
        f"select id, business, name, email, message, source, status, notes, "
        f"created_at, updated_at from {_T} where id = %s::uuid", (lead_id,))
    return cur.fetchone()


def update(cur, lead_id: str, status: str, notes: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"invalid status: {status}")
    cur.execute(
        f"update {_T} set status = %s, notes = %s where id = %s::uuid",
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
