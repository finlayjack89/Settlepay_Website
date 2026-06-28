"""Postgres access (Supabase, service-role). Server-side only — never the browser.

Connects via DATABASE_URL and pins search_path to the outreach schema (then
public), so unqualified table names hit the pipeline's own schema while the
website's inbound enquiry source is referenced explicitly as public.<table>.
"""
from __future__ import annotations
import contextlib

import psycopg

from . import config


def connect() -> "psycopg.Connection":
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set (outreach/.env)")
    conn = psycopg.connect(config.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute(f'set search_path to "{config.DB_SCHEMA}", public')
    conn.commit()
    return conn


@contextlib.contextmanager
def cursor(commit: bool = True):
    """Yield a cursor; commit on clean exit (or rollback if commit=False)."""
    conn = connect()
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit() if commit else conn.rollback()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping() -> bool:
    with cursor(commit=False) as cur:
        cur.execute("select 1")
        return cur.fetchone()[0] == 1
