"""SettlePay operations console — the inbound side (website enquiries, and later
schedule/bookings).

The design system here is deliberately identical to the outreach operator console
(`outreach/outreach/web.py`) — same Satoshi type, brand #0F172A, action #3B82F6,
pill buttons, soft blue-tinted shadows, sidebar shell — so the two consoles fold
into one operations surface later (shared `_STYLE`/`_shell` should be DRY'd then).

This module is pure rendering (no DB) so the pages can be previewed with mock data.
Routes + DB live in app.py / db.py.
"""
from __future__ import annotations
import html
from datetime import datetime, timezone

NAV = [
    ("/", "Dashboard", "grid"),
    ("/enquiries", "Enquiries", "inbox"),
    ("/schedule", "Schedule", "calendar"),
    ("/settings", "Settings", "cog"),
]

ICONS = {
    "grid": "M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z",
    "inbox": "M2.25 13.5h3.86a2.25 2.25 0 012.012 1.244l.256.512a2.25 2.25 0 002.013 1.244h3.218a2.25 2.25 0 002.013-1.244l.256-.512a2.25 2.25 0 012.013-1.244h3.859m-19.5.338V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18v-4.162c0-.224-.034-.447-.1-.661L19.24 5.338a2.25 2.25 0 00-2.15-1.588H6.911a2.25 2.25 0 00-2.15 1.588L2.35 13.177a2.25 2.25 0 00-.1.661z",
    "calendar": "M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5",
    "cog": "M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
}

# Inbound enquiry status -> (label, semantic colour key). Mirrors the marketing
# functional palette; blue (action) reserved for in-flight states.
STATUS_STYLE = {
    "new": ("New", "warning"),
    "contacted": ("Contacted", "neutral"),
    "quoted": ("Quoted", "info"),
    "won": ("Won", "success"),
    "client": ("Client", "success"),
    "lost": ("Lost", "muted"),
}
PIPELINE_ORDER = ["new", "contacted", "quoted", "won", "client", "lost"]

# Identical to the outreach console's _STYLE (shared design system — DRY on merge).
_STYLE = """
:root{
  --brand:#0F172A; --action:#3B82F6; --action-hover:#2563EB; --bg:#F1F5F9; --white:#fff;
  --success:#10B981; --warning:#F59E0B; --info:#8B5CF6; --error:#DC2626;
  --line:rgba(15,23,42,.08); --muted:rgba(15,23,42,.55);
  --radius-card:20px; --radius-tile:14px; --radius-input:8px; --radius-pill:100px;
  --shadow-sm:0 2px 8px rgba(30,58,138,.06);
  --shadow-md:0 4px 20px rgba(30,58,138,.06),0 1px 3px rgba(30,58,138,.03);
  --font:'Satoshi',system-ui,-apple-system,sans-serif;
  --mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:var(--font);background:var(--bg);color:var(--brand);line-height:1.55;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.app{display:flex;min-height:100vh}
.sidebar{width:248px;flex-shrink:0;background:var(--brand);color:#fff;display:flex;flex-direction:column;
  position:sticky;top:0;height:100vh;padding:1.5rem 1rem}
.brand{display:flex;flex-direction:column;gap:.1rem;padding:.25rem .75rem 1.5rem}
.brand b{font-size:1.15rem;font-weight:700;letter-spacing:-.02em}
.brand span{font-size:.72rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:rgba(255,255,255,.45)}
.nav{display:flex;flex-direction:column;gap:.25rem;flex:1}
.nav a{display:flex;align-items:center;gap:.7rem;padding:.6rem .75rem;border-radius:12px;
  font-size:.9rem;font-weight:500;color:rgba(255,255,255,.7);transition:all .15s}
.nav a:hover{background:rgba(255,255,255,.06);color:#fff}
.nav a.active{background:var(--action);color:#fff;box-shadow:0 4px 12px rgba(59,130,246,.35)}
.nav a.soon{opacity:.35;cursor:default}
.nav svg{width:18px;height:18px;flex-shrink:0}
.nav .tag{margin-left:auto;font-size:.6rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  background:rgba(255,255,255,.12);padding:.1rem .4rem;border-radius:6px}
.side-status{margin-top:1rem;padding:.85rem;border-radius:12px;background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.08);font-size:.74rem;color:rgba(255,255,255,.7)}
.side-status .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:.4rem}
.dot-amber{background:var(--warning)} .dot-green{background:var(--success)} .dot-red{background:var(--error)}
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  padding:1.4rem 2.25rem;background:var(--white);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.topbar h1{font-size:1.35rem;font-weight:700;letter-spacing:-.02em}
.topbar .sub{font-size:.82rem;color:var(--muted);margin-top:.1rem}
.content{padding:2rem 2.25rem 3rem;max-width:1180px;width:100%}
.statpill{display:inline-flex;align-items:center;gap:.45rem;font-size:.76rem;font-weight:700;
  padding:.4rem .8rem;border-radius:var(--radius-pill);background:rgba(16,185,129,.1);color:#0f9d6c}
.statpill .dot{width:7px;height:7px;border-radius:50%;background:var(--success)}
.panel{background:var(--white);border-radius:var(--radius-card);box-shadow:var(--shadow-md);
  padding:1.5rem 1.65rem;margin-bottom:1.5rem}
.panel h2{font-size:1.02rem;font-weight:700;letter-spacing:-.01em;margin-bottom:.25rem}
.panel .hint{font-size:.8rem;color:var(--muted);margin-bottom:1.1rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1rem;margin-bottom:1.5rem}
.tile{background:var(--white);border-radius:var(--radius-tile);box-shadow:var(--shadow-sm);padding:1.1rem 1.2rem;
  border:1px solid var(--line)}
.tile .n{font-size:1.9rem;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.tile .l{font-size:.78rem;font-weight:600;color:var(--muted);margin-top:.1rem}
.tile .s{font-size:.72rem;color:var(--muted);margin-top:.35rem}
.tile.accent{background:var(--brand);border-color:var(--brand)}
.tile.accent .n{color:#fff} .tile.accent .l,.tile.accent .s{color:rgba(255,255,255,.6)}
.funnel{display:flex;flex-direction:column;gap:.65rem}
.frow{display:grid;grid-template-columns:170px 1fr 96px;align-items:center;gap:1rem}
.frow .fl{font-size:.83rem;font-weight:600}
.ftrack{background:var(--bg);border-radius:var(--radius-pill);height:26px;overflow:hidden}
.ffill{height:100%;border-radius:var(--radius-pill);background:linear-gradient(90deg,var(--action),#60a5fa);
  min-width:2px;transition:width .4s}
.ffill.green{background:linear-gradient(90deg,#10B981,#34d399)}
.ffill.grey{background:linear-gradient(90deg,#94a3b8,#cbd5e1)}
.ffill.amber{background:linear-gradient(90deg,#F59E0B,#fbbf24)}
.frow .fn{font-size:.82rem;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
.frow .fn small{display:block;font-weight:500;color:var(--muted);font-size:.7rem}
table{border-collapse:collapse;width:100%;font-size:.85rem}
th{text-align:left;font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--muted);padding:.5rem .65rem;border-bottom:1px solid var(--line)}
td{padding:.6rem .65rem;border-bottom:1px solid var(--line);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr.clk:hover{background:var(--bg);cursor:pointer}
.num{text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-flex;align-items:center;font-size:.72rem;font-weight:700;padding:.22rem .6rem;border-radius:var(--radius-pill);white-space:nowrap}
.b-success{background:rgba(16,185,129,.12);color:#0f9d6c}
.b-info{background:rgba(139,92,246,.12);color:#7c3aed}
.b-warning{background:rgba(245,158,11,.14);color:#b45309}
.b-error{background:rgba(220,38,38,.1);color:#dc2626}
.b-muted{background:rgba(15,23,42,.06);color:var(--muted)}
.b-neutral{background:rgba(59,130,246,.1);color:var(--action)}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.1rem}
.chip{font-size:.78rem;font-weight:600;padding:.35rem .8rem;border-radius:var(--radius-pill);
  background:var(--white);border:1px solid var(--line);color:var(--muted)}
.chip.active{background:var(--brand);color:#fff;border-color:var(--brand)}
.chip b{margin-left:.35rem;opacity:.7}
textarea{width:100%;min-height:7rem;font:13.5px/1.6 var(--mono);padding:.8rem;border:1px solid var(--line);
  border-radius:var(--radius-input);background:#fcfcfd;resize:vertical}
input[type=text],input:not([type]),select{padding:.5rem .7rem;border:1px solid var(--line);border-radius:var(--radius-input);font:inherit;font-size:.85rem;min-width:200px;background:#fff}
label.fld{display:block;font-size:.78rem;font-weight:600;color:var(--muted);margin:.9rem 0 .35rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;font:inherit;font-size:.85rem;font-weight:600;
  border:none;border-radius:var(--radius-pill);padding:.6rem 1.4rem;cursor:pointer;transition:all .15s}
.btn-primary{background:var(--action);color:#fff;box-shadow:0 2px 8px rgba(59,130,246,.25)}
.btn-primary:hover{background:var(--action-hover);transform:translateY(-1px)}
.btn-ghost{background:var(--white);color:var(--brand);border:1.5px solid var(--line)}
.btn-ghost:hover{border-color:rgba(15,23,42,.3)}
.row{display:flex;gap:.75rem;align-items:flex-end;flex-wrap:wrap}
.note{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);color:#92400e;
  padding:.75rem 1rem;border-radius:var(--radius-input);font-size:.82rem;margin-bottom:1.5rem}
.ok{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.25);color:#0f7a55;
  padding:.7rem .9rem;border-radius:var(--radius-input);font-size:.84rem;margin-bottom:1rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}
.kv{display:grid;grid-template-columns:150px 1fr;gap:.4rem .8rem;font-size:.85rem}
.kv dt{color:var(--muted);font-weight:600} .kv dd{font-weight:500}
.body-box{font:14px/1.7 var(--font);background:#fcfcfd;border:1px solid var(--line);
  border-radius:var(--radius-input);padding:1rem;white-space:pre-wrap}
.muted{color:var(--muted)} .empty{color:var(--muted);font-size:.88rem;padding:1.5rem 0;text-align:center}
@media(max-width:820px){.sidebar{display:none}.two{grid-template-columns:1fr}.frow{grid-template-columns:120px 1fr 70px}}
"""


def _icon(name: str) -> str:
    raw = ICONS.get(name, "")
    if not raw:
        return ""
    parts = raw.split(" M")
    subpaths = [parts[0]] + ["M" + p for p in parts[1:]]
    paths = "".join(
        f'<path stroke-linecap="round" stroke-linejoin="round" d="{d}"/>' for d in subpaths)
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">{paths}</svg>'


def _badge(status: str) -> str:
    label, kind = STATUS_STYLE.get(status, (status, "neutral"))
    return f'<span class="badge b-{kind}">{html.escape(label)}</span>'


def _ago(dt: datetime | None) -> str:
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (now - dt).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 7 * 86400:
        return f"{int(secs // 86400)}d ago"
    return dt.strftime("%d %b %Y")


def _shell(active: str, title: str, sub: str, body: str, side_status: str) -> str:
    nav = ""
    for href, label, icon in NAV:
        if label == "Schedule":
            nav += f'<a class="soon">{_icon(icon)}<span>{label}</span><span class="tag">Soon</span></a>'
            continue
        cls = "active" if href == active else ""
        nav += f'<a class="{cls}" href="{href}">{_icon(icon)}<span>{label}</span></a>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · SettlePay Console</title>
<link rel="preconnect" href="https://api.fontshare.com" crossorigin>
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap">
<style>{_STYLE}</style></head><body><div class="app">
<aside class="sidebar">
  <div class="brand"><b>SettlePay</b><span>Operations</span></div>
  <nav class="nav">{nav}</nav>
  <div class="side-status">{side_status}</div>
</aside>
<main class="main">
  <div class="topbar"><div><h1>{html.escape(title)}</h1><div class="sub">{html.escape(sub)}</div></div>
    <span class="statpill"><span class="dot"></span>Live enquiries</span></div>
  <div class="content">{body}</div>
</main></div></body></html>"""


def _side_status(db_ok: bool, source_table: str) -> str:
    if db_ok:
        line = '<span class="dot dot-green"></span>Connected'
    else:
        line = '<span class="dot dot-red"></span>DB not configured'
    return (f"{line}<br><span class=\"muted\" style=\"color:rgba(255,255,255,.45);font-size:.7rem\">"
            f"Source: public.{html.escape(source_table)} · Schedule: not connected</span>")


# --------------------------------------------------------------------------- #
def dashboard(o: dict, pipeline: list[tuple[str, int]], recent: list[dict], side: str) -> str:
    total = o["total"] or 0
    conv = (100.0 * (o["won"] + o["client"]) / total) if total else 0.0
    tiles = [
        ("accent", o["total"], "Enquiries", "all time"),
        ("", o["new"], "New", "awaiting first contact"),
        ("", o["this_week"], "This week", "last 7 days"),
        ("", o["contacted"] + o["quoted"], "In progress", "contacted / quoted"),
        ("", o["won"] + o["client"], "Won", f'{o["client"]} now clients'),
        ("", f"{conv:.0f}%", "Conversion", "won + client of total"),
    ]
    kpis = "".join(
        f'<div class="tile {cls}"><div class="n">{n}</div><div class="l">{l}</div><div class="s">{s}</div></div>'
        for cls, n, l, s in tiles)

    pmap = dict(pipeline)
    rows = ""
    for st in PIPELINE_ORDER:
        n = pmap.get(st, 0)
        w = (100.0 * n / total) if total else 0.0
        colour = {"won": "green", "client": "green", "lost": "grey", "new": "amber"}.get(st, "")
        label = STATUS_STYLE[st][0]
        rows += (f'<div class="frow"><div class="fl">{label}</div>'
                 f'<div class="ftrack"><div class="ffill {colour}" style="width:{max(w,1):.1f}%"></div></div>'
                 f'<div class="fn">{n}<small>{w:.0f}%</small></div></div>')

    feed = "".join(
        f'<tr class="clk" onclick="location.href=\'/enquiry/{html.escape(str(r["id"]))}\'">'
        f'<td><b>{html.escape(r["business"])}</b><br><span class="muted" style="font-size:.74rem">{html.escape(r["name"])}</span></td>'
        f'<td>{_badge(r["status"])}</td>'
        f'<td class="num muted">{_ago(r["created_at"])}</td></tr>'
        for r in recent) or '<tr><td colspan=3 class="empty">No enquiries yet.</td></tr>'

    body = f"""
<div class="kpis">{kpis}</div>
<div class="two">
  <div class="panel"><h2>Pipeline</h2>
    <div class="hint">Where your inbound enquiries currently stand, as a share of all enquiries.</div>
    <div class="funnel">{rows}</div>
  </div>
  <div class="panel"><h2>Latest enquiries</h2>
    <div class="hint">Most recent submissions from the website form. Click to open.</div>
    <table><tr><th>Business</th><th>Status</th><th class="num">Received</th></tr>{feed}</table>
  </div>
</div>"""
    return _shell("/", "Dashboard", "Inbound enquiries at a glance", body, side)


# --------------------------------------------------------------------------- #
def enquiries(counts: dict, rows: list[dict], active: str, side: str) -> str:
    total = sum(counts.values())
    chips = f'<a class="chip {"active" if not active else ""}" href="/enquiries">All <b>{total}</b></a>'
    for st in PIPELINE_ORDER:
        if counts.get(st):
            chips += (f'<a class="chip {"active" if active == st else ""}" href="/enquiries?status={st}">'
                      f'{STATUS_STYLE[st][0]} <b>{counts[st]}</b></a>')

    trs = ""
    for r in rows:
        trs += (f'<tr class="clk" onclick="location.href=\'/enquiry/{html.escape(str(r["id"]))}\'">'
                f'<td><b>{html.escape(r["business"])}</b></td>'
                f'<td>{html.escape(r["name"])}</td>'
                f'<td><a href="mailto:{html.escape(r["email"])}" onclick="event.stopPropagation()">{html.escape(r["email"])}</a></td>'
                f'<td>{_badge(r["status"])}</td>'
                f'<td class="num muted">{_ago(r["created_at"])}</td></tr>')
    trs = trs or '<tr><td colspan=5 class="empty">No enquiries match this filter.</td></tr>'

    body = f"""<div class="chips">{chips}</div>
<div class="panel"><table>
<tr><th>Business</th><th>Name</th><th>Email</th><th>Status</th><th class="num">Received</th></tr>
{trs}</table>
<p class="muted" style="margin-top:1rem;font-size:.78rem">Showing {len(rows)} enquir{"y" if len(rows)==1 else "ies"}.</p>
</div>"""
    return _shell("/enquiries", "Enquiries", "Every inbound enquiry — your CRM", body, side)


# --------------------------------------------------------------------------- #
def enquiry_detail(lead: dict, side: str, saved: bool = False) -> str:
    options = "".join(
        f'<option value="{st}"{" selected" if lead["status"] == st else ""}>{STATUS_STYLE[st][0]}</option>'
        for st in PIPELINE_ORDER)
    saved_html = '<div class="ok">Saved.</div>' if saved else ""
    body = f"""
{saved_html}
<div class="two">
  <div class="panel"><h2>{html.escape(lead["business"])}</h2>
    <div class="hint">Enquiry received {_ago(lead["created_at"])}</div>
    <dl class="kv">
      <dt>Contact</dt><dd>{html.escape(lead["name"])}</dd>
      <dt>Email</dt><dd><a href="mailto:{html.escape(lead["email"])}">{html.escape(lead["email"])}</a></dd>
      <dt>Status</dt><dd>{_badge(lead["status"])}</dd>
      <dt>Source</dt><dd>{html.escape(lead.get("source") or "—")}</dd>
      <dt>Received</dt><dd>{lead["created_at"].strftime("%d %b %Y, %H:%M") if lead.get("created_at") else "—"}</dd>
    </dl>
    <h2 style="margin-top:1.5rem">Their message</h2>
    <div class="body-box" style="margin-top:.6rem">{html.escape(lead["message"])}</div>
  </div>
  <div class="panel"><h2>Manage</h2>
    <div class="hint">Move the enquiry through your pipeline and keep private notes.</div>
    <form method="post" action="/enquiry/{html.escape(str(lead["id"]))}">
      <label class="fld">Status</label>
      <select name="status">{options}</select>
      <label class="fld">Notes (private — not shown to the enquirer)</label>
      <textarea name="notes">{html.escape(lead.get("notes") or "")}</textarea>
      <div class="row" style="margin-top:1rem">
        <button class="btn btn-primary" type="submit">Save</button>
        <a class="btn btn-ghost" href="mailto:{html.escape(lead["email"])}?subject=Re%3A%20your%20SettlePay%20enquiry">Reply by email</a>
      </div>
    </form>
  </div>
</div>
<p class="muted" style="font-size:.8rem"><a href="/enquiries">&larr; Back to enquiries</a></p>"""
    return _shell("/enquiries", lead["business"], "Enquiry record", body, side)


# --------------------------------------------------------------------------- #
def schedule(side: str) -> str:
    body = """
<div class="note">Consultations &amp; bookings will appear here once Microsoft Bookings + the Microsoft Graph
connection are live. That needs a Teams/Bookings-capable M365 licence and a one-time Entra app registration —
see <b>Docs/BOOKING-CRM-PLAN.md</b>. Until then this view is a placeholder.</div>
<div class="panel"><div class="empty">No schedule connected yet.</div></div>"""
    return _shell("/schedule", "Schedule", "Consultations & bookings (coming soon)", body, side)


# --------------------------------------------------------------------------- #
def settings(cfg: dict, side: str) -> str:
    body = f"""<div class="two">
  <div class="panel"><h2>Data source</h2>
    <div class="hint">Where this console reads from. Read-only — change via env + restart.</div>
    <dl class="kv">
      <dt>Database</dt><dd>{'<span class="badge b-success">connected</span>' if cfg["db_ok"] else '<span class="badge b-error">not configured</span>'}</dd>
      <dt>Enquiries table</dt><dd>public.{html.escape(cfg["source_table"])}</dd>
      <dt>Project ref</dt><dd>{html.escape(cfg.get("project_ref") or "—")}</dd>
      <dt>Endpoint</dt><dd class="muted" style="font-size:.78rem">{html.escape(cfg.get("endpoint") or "—")}</dd>
    </dl></div>
  <div class="panel"><h2>Integrations</h2>
    <div class="hint">What's wired vs pending.</div>
    <dl class="kv">
      <dt>Enquiry capture</dt><dd><span class="badge b-success">live</span></dd>
      <dt>Branded emails</dt><dd><span class="badge b-success">live (01/02)</span></dd>
      <dt>Microsoft Graph</dt><dd><span class="badge b-muted">not configured</span> <span class="muted">(schedule/Teams)</span></dd>
      <dt>Bookings</dt><dd><span class="badge b-muted">pending licence</span></dd>
    </dl></div>
</div>
<div class="note">This console is <b>localhost-only and unauthenticated</b> — do not expose it publicly. It mirrors
the outreach operator console's design system so the two fold into one operations surface later.</div>"""
    return _shell("/settings", "Settings", "Data source & integration status (read-only)", body, side)
