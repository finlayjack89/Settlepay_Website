#!/usr/bin/env python3
"""Read-only SQL scalar runner for the outreach-build FLOOR (verify.sh).

Loop-maker-owned and deterministic — this is NOT part of the pipeline the build
loop writes, so the floor stays independent of the loop's own code. It runs a
single read-only query and prints the first column of the first row (or nothing).

It refuses anything that isn't a single bare SELECT/WITH, sets the session
READ ONLY, and sets search_path to the outreach schema (then public) so bare
table names resolve to outreach.* while the website's inbound enquiry source must
be referenced explicitly as public.<table>.

Connection: DATABASE_URL (Supabase pooler / service-role Postgres URL), exported
into the environment by verify.sh from outreach/.env.

Usage:
    floor_db.py scalar "SELECT count(*) FROM leads"   # -> outreach.leads
"""
import os
import re
import sys


def fail(msg, code):
    print(f"floor_db: {msg}", file=sys.stderr)
    sys.exit(code)


def main():
    if len(sys.argv) < 3 or sys.argv[1] != "scalar":
        fail('usage: floor_db.py scalar "SELECT ..."', 2)
    sql = sys.argv[2].strip().rstrip(";")
    if not re.match(r"(?is)^\s*(select|with)\b", sql) or ";" in sql:
        fail("only a single read-only SELECT/WITH is allowed", 2)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        fail("DATABASE_URL not set", 3)
    schema = os.environ.get("DB_SCHEMA", "outreach")

    try:
        import psycopg  # psycopg3 — a pipeline dependency
        connect = psycopg.connect
    except ImportError:
        try:
            import psycopg2
            connect = psycopg2.connect
        except ImportError:
            fail("psycopg not installed", 3)

    try:
        conn = connect(dsn)
        try:
            cur = conn.cursor()
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f'SET search_path TO "{schema}", public')
            cur.execute(sql)
            row = cur.fetchone()
            if row is not None and row[0] is not None:
                print(row[0])
        finally:
            conn.rollback()
            conn.close()
    except Exception as e:  # connection refused, missing table, bad SQL -> empty + nonzero
        fail(str(e).splitlines()[0], 4)


if __name__ == "__main__":
    main()
