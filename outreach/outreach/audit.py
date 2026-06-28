"""audit_log writer — one row per lead decision (source + lawful_basis + reason).

Every lead the firewall touches gets a row with lawful_basis='legitimate
interests' and the classification reason (see CONTEXT.md, phase C).
"""
from __future__ import annotations
import json
from typing import Any, Optional

from . import config, db

LEGITIMATE_INTERESTS = "legitimate interests"


def record(
    company_number: Optional[str],
    event: str,
    *,
    source: Optional[str] = None,
    lawful_basis: Optional[str] = None,
    reason: Optional[str] = None,
    detail: Optional[dict[str, Any]] = None,
    cur=None,
) -> None:
    """Insert an audit row. If `cur` is given, use the caller's transaction
    (so it commits/rolls back atomically with their work); otherwise open one."""
    sql = (
        f'insert into "{config.DB_SCHEMA}".audit_log '
        "(company_number, event, source, lawful_basis, reason, detail) "
        "values (%s, %s, %s, %s, %s, %s)"
    )
    params = (
        company_number, event, source, lawful_basis, reason,
        json.dumps(detail) if detail is not None else None,
    )
    if cur is not None:
        cur.execute(sql, params)
    else:
        with db.cursor() as c:
            c.execute(sql, params)
