"""SettlePay operations console — FastAPI routes (inbound enquiries side).

LOCALHOST-ONLY, no auth (same posture as the outreach console) — never expose it
publicly. Run:

    cd console
    cp .env.example .env          # fill DATABASE_URL (Supabase session pooler)
    python -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/uvicorn app:app --port 8799
    # open http://localhost:8799/
"""
from __future__ import annotations

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

import db
import views

app = FastAPI(title="SettlePay — operations console")

PROJECT_REF = "xqpbcoldcqfxfwhcqlcy"
ENDPOINT = "https://xqpbcoldcqfxfwhcqlcy.supabase.co/functions/v1/enquiry"

_EMPTY = {"total": 0, "new": 0, "contacted": 0, "quoted": 0, "won": 0,
          "client": 0, "lost": 0, "this_week": 0}


def _side() -> str:
    return views._side_status(db.db_ok(), db.SOURCE_TABLE)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    if not db.db_ok():
        return views.dashboard(dict(_EMPTY), [], [], _side())
    with db.cursor() as cur:
        o = db.overview(cur)
        recent = db.recent(cur, 8)
    pipeline = [(st, o.get(st, 0)) for st in views.PIPELINE_ORDER]
    return views.dashboard(o, pipeline, recent, _side())


@app.get("/enquiries", response_class=HTMLResponse)
def enquiries(status: str = ""):
    if not db.db_ok():
        return views.enquiries({}, [], status, _side())
    with db.cursor() as cur:
        counts = db.status_counts(cur)
        rows = db.list_enquiries(cur, status)
    return views.enquiries(counts, rows, status, _side())


@app.get("/enquiry/{lead_id}", response_class=HTMLResponse)
def enquiry_detail(lead_id: str, saved: int = 0):
    if not db.db_ok():
        return HTMLResponse(_notfound("Database not configured."), status_code=503)
    try:
        with db.cursor() as cur:
            lead = db.get(cur, lead_id)
    except Exception:
        lead = None
    if not lead:
        return HTMLResponse(_notfound("Enquiry not found."), status_code=404)
    return views.enquiry_detail(lead, _side(), saved=bool(saved))


@app.post("/enquiry/{lead_id}")
def enquiry_update(lead_id: str, status: str = Form(...), notes: str = Form("")):
    try:
        with db.cursor() as cur:
            db.update(cur, lead_id, status, notes)
    except Exception:
        return RedirectResponse(f"/enquiry/{lead_id}", status_code=303)
    return RedirectResponse(f"/enquiry/{lead_id}?saved=1", status_code=303)


@app.get("/schedule", response_class=HTMLResponse)
def schedule():
    return views.schedule(_side())


@app.get("/settings", response_class=HTMLResponse)
def settings():
    return views.settings({
        "db_ok": db.db_ok(),
        "source_table": db.SOURCE_TABLE,
        "project_ref": PROJECT_REF,
        "endpoint": ENDPOINT,
    }, _side())


def _notfound(msg: str) -> str:
    return views._shell("/enquiries", "Not found", "",
                        f'<div class="panel"><div class="empty">{msg}</div></div>', _side())
