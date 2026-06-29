"""Apply SQL migrations in migrations/*.sql (idempotent). CLI: python -m outreach.migrate"""
from __future__ import annotations
import pathlib

from . import config, db

MIGRATIONS_DIR = config.PROJECT_ROOT / "migrations"


def apply() -> list[str]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("no migrations found")
        return []
    conn = db.connect()
    applied: list[str] = []
    try:
        for f in files:
            with conn.cursor() as cur:
                cur.execute(f.read_text())
            conn.commit()
            applied.append(f.name)
            print(f"applied {f.name}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return applied


if __name__ == "__main__":
    apply()
