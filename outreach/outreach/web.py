"""Minimal LOCAL operator UI — phase F approval queue + read-only dashboard.

Localhost only, single operator, no auth (do not expose publicly). Approval reuses
outreach.review (envelope re-checked, audited, body_original immutable). This UI
does NOT send: approving only advances a draft to 'approved'; sending stays in the
gated send path (G-SEND). Run:

    cd outreach && .venv/bin/uvicorn outreach.web:app --port 8787
    # then open http://localhost:8787
"""
from __future__ import annotations
import html

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db, review
from .sequence import graduation_thresholds

app = FastAPI(title="SettlePay outreach — operator")


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset=utf-8><title>{title}</title><style>
body{{font:15px/1.55 system-ui,-apple-system,sans-serif;max-width:820px;margin:2rem auto;padding:0 1rem;color:#111}}
a{{color:#3B82F6;text-decoration:none}} .muted{{color:#666}} .warn{{color:#b91c1c}}
.card{{border:1px solid #e5e7eb;border-radius:8px;padding:1rem;margin:1rem 0}}
textarea{{width:100%;min-height:9rem;font:14px/1.5 ui-monospace,monospace;padding:.5rem}}
input{{padding:.35rem .5rem}} button{{background:#111;color:#fff;border:0;border-radius:100px;padding:.5rem 1rem;cursor:pointer}}
button.secondary{{background:#fff;color:#111;border:1px solid #ccc}}
table{{border-collapse:collapse;width:100%}} td,th{{text-align:left;padding:.3rem .6rem;border-bottom:1px solid #eee}}
nav a{{margin-right:1rem}}</style></head><body>
<nav><a href="/">Approval queue</a><a href="/dashboard">Dashboard</a></nav>{body}</body></html>"""


@app.get("/", response_class=HTMLResponse)
def queue():
    with db.cursor(commit=False) as cur:
        rows = review.list_pending(cur)
    cards = "".join(
        f'<div class=card><b>{html.escape(name)}</b> '
        f'<span class=muted>({html.escape(cn)})</span><br>'
        f'<a href="/draft/{did}">Review &rarr;</a></div>'
        for did, cn, name, _body in rows
    ) or "<p class=muted>No drafts awaiting approval.</p>"
    return _page("Approval queue", f"<h1>Approval queue</h1><p class=muted>{len(rows)} awaiting</p>{cards}")


@app.get("/draft/{draft_id}", response_class=HTMLResponse)
def draft_view(draft_id: str, err: str = ""):
    with db.cursor(commit=False) as cur:
        cur.execute(
            "select d.company_number, l.company_name, d.body_original, d.status "
            "from outreach.drafts d join outreach.leads l on l.company_number=d.company_number "
            "where d.id=%s", (draft_id,))
        row = cur.fetchone()
    if not row:
        return HTMLResponse(_page("Not found", "<p>Draft not found.</p>"), status_code=404)
    cn, name, body, status = row
    errhtml = f'<p class=warn>{html.escape(err)}</p>' if err else ""
    body_html = f"""<h1>{html.escape(name)} <span class=muted>({html.escape(cn)})</span></h1>
<p class=muted>status: {html.escape(status)}</p>{errhtml}
<form method=post action="/approve/{draft_id}">
  <p>Reviewer: <input name=reviewer required></p>
  <p class=muted>Edit to approve a revised version (leave unchanged to approve as-is).
  body_original stays immutable; compliance is re-checked on save.</p>
  <textarea name=edited>{html.escape(body)}</textarea>
  <p>Note: <input name=note size=52></p>
  <button type=submit>Approve</button>
</form>
<form method=post action="/reject/{draft_id}" style="margin-top:1.5rem">
  <p>Reviewer: <input name=reviewer required> &nbsp; Note: <input name=note size=40></p>
  <button class=secondary type=submit>Reject</button>
</form>"""
    return _page("Review draft", body_html)


@app.post("/approve/{draft_id}")
def approve(draft_id: str, reviewer: str = Form(...), edited: str = Form(""), note: str = Form("")):
    try:
        with db.cursor(commit=False) as cur:
            cur.execute("select body_original from outreach.drafts where id=%s", (draft_id,))
            r = cur.fetchone()
        original = (r[0] if r else "") or ""
        edit_arg = None if edited.strip() == original.strip() else edited  # unchanged => approve-as-is
        review.approve(draft_id, reviewer, edited=edit_arg, note=note or None)
    except Exception as e:  # envelope violation, already-decided, etc. -> show on the page
        return RedirectResponse(f"/draft/{draft_id}?err={html.escape(str(e))}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/reject/{draft_id}")
def reject(draft_id: str, reviewer: str = Form(...), note: str = Form("")):
    try:
        review.reject(draft_id, reviewer, note=note or None)
    except Exception as e:
        return RedirectResponse(f"/draft/{draft_id}?err={html.escape(str(e))}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with db.cursor(commit=False) as cur:
        cur.execute("select state::text, count(*) from outreach.leads group by state order by count(*) desc")
        states = cur.fetchall()
        cur.execute(
            "select count(*) filter (where status in ('approved','sent')), "
            "count(*) filter (where status in ('approved','sent') and body_final=body_original), "
            "count(*) from outreach.drafts")
        approved, unedited, total_drafts = cur.fetchone()
        cur.execute("select mode, count(*) from outreach.sends group by mode")
        sends = cur.fetchall()
    g = graduation_thresholds()
    unedited_rate = (unedited / approved) if approved else 0.0
    state_rows = "".join(f"<tr><td>{html.escape(s)}</td><td>{n}</td></tr>" for s, n in states)
    send_rows = "".join(f"<tr><td>{html.escape(m)}</td><td>{n}</td></tr>" for m, n in sends) \
        or "<tr><td colspan=2 class=muted>no sends</td></tr>"
    body = f"""<h1>Dashboard</h1>
<h3>Leads by state</h3><table>{state_rows}</table>
<h3>Sends</h3><table>{send_rows}</table>
<h3>Graduation thresholds (per-vertical auto-send target)</h3><table>
<tr><th>metric</th><th>now</th><th>target</th></tr>
<tr><td>reviewed drafts</td><td>{total_drafts}</td><td class=muted>&ge; {g.get('min_reviewed_drafts_per_vertical')}</td></tr>
<tr><td>approved unedited rate</td><td>{unedited_rate:.0%} ({unedited}/{approved})</td><td class=muted>&ge; {g.get('min_approved_unedited_rate',0):.0%}</td></tr>
<tr><td>bounce rate</td><td class=muted>n/a (no live sends)</td><td class=muted>&lt; {g.get('max_bounce_rate',0):.0%}</td></tr>
<tr><td>spot check</td><td class=muted>1 in {int(1/g['spot_check_ratio']) if g.get('spot_check_ratio') else '?'}</td><td class=muted>policy</td></tr>
</table>
<p class=muted>Live sending stays gated behind G-SEND regardless of this screen.</p>"""
    return _page("Dashboard", body)
