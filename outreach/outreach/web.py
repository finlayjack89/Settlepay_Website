"""LOCAL operator console for the SettlePay outreach pipeline.

A single-operator, localhost-only web app (no auth — do not expose publicly). It is
the human side of the pipeline: a dashboard over the live funnel, a CRM-style lead
browser, the approval queue (the gate before any send), and a read-only settings
view of the runtime safety posture.

Design system mirrors the SettlePay marketing site (Satoshi, brand #0F172A, action
#3B82F6, pill buttons, soft blue-tinted shadows) so this console can grow into the
operations/CRM surface without a restyle.

Approval reuses outreach.review (envelope re-checked, audited, body_original
immutable). Approving only advances a draft to 'approved'; sending stays gated
behind G-SEND. Run:

    cd outreach && .venv/bin/uvicorn outreach.web:app --port 8787
    # then open http://localhost:8787/dashboard
"""
from __future__ import annotations
import html

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from . import config, db, review, stats
from .sequence import graduation_thresholds, load_sequence_config

app = FastAPI(title="SettlePay Outreach — operator console")

NAV = [
    ("/dashboard", "Dashboard", "grid"),
    ("/queue", "Approval queue", "inbox"),
    ("/leads", "Leads", "users"),
    ("/settings", "Settings", "cog"),
]

ICONS = {
    "grid": "M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z",
    "inbox": "M2.25 13.5h3.86a2.25 2.25 0 012.012 1.244l.256.512a2.25 2.25 0 002.013 1.244h3.218a2.25 2.25 0 002.013-1.244l.256-.512a2.25 2.25 0 012.013-1.244h3.859m-19.5.338V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18v-4.162c0-.224-.034-.447-.1-.661L19.24 5.338a2.25 2.25 0 00-2.15-1.588H6.911a2.25 2.25 0 00-2.15 1.588L2.35 13.177a2.25 2.25 0 00-.1.661z",
    "users": "M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z",
    "cog": "M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z M15 12a3 3 0 11-6 0 3 3 0 016 0z",
}

# lead state -> (label, semantic colour key). Colours map to the design system's
# functional palette; blue stays reserved for in-flight / action states.
STATE_STYLE = {
    "discovered": ("Discovered", "neutral"),
    "enriched": ("Enriched", "info"),
    "drafted": ("Drafted", "info"),
    "awaiting_approval": ("Awaiting approval", "warning"),
    "approved": ("Approved", "success"),
    "sending": ("Sending", "info"),
    "sent": ("Sent", "success"),
    "replied": ("Replied", "success"),
    "suppressed": ("Suppressed (PECR)", "muted"),
    "rejected": ("Rejected", "error"),
    "discarded": ("Discarded", "muted"),
    "bounced": ("Bounced", "error"),
}

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
/* sidebar */
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
/* main */
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.topbar{display:flex;align-items:center;justify-content:space-between;gap:1rem;
  padding:1.4rem 2.25rem;background:var(--white);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:10}
.topbar h1{font-size:1.35rem;font-weight:700;letter-spacing:-.02em}
.topbar .sub{font-size:.82rem;color:var(--muted);margin-top:.1rem}
.content{padding:2rem 2.25rem 3rem;max-width:1180px;width:100%}
.statpill{display:inline-flex;align-items:center;gap:.45rem;font-size:.76rem;font-weight:700;
  padding:.4rem .8rem;border-radius:var(--radius-pill);background:rgba(245,158,11,.1);color:#b45309}
.statpill .dot{width:7px;height:7px;border-radius:50%;background:var(--warning)}
/* panels + tiles */
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
/* funnel */
.funnel{display:flex;flex-direction:column;gap:.65rem}
.frow{display:grid;grid-template-columns:170px 1fr 96px;align-items:center;gap:1rem}
.frow .fl{font-size:.83rem;font-weight:600}
.ftrack{background:var(--bg);border-radius:var(--radius-pill);height:26px;overflow:hidden}
.ffill{height:100%;border-radius:var(--radius-pill);background:linear-gradient(90deg,var(--action),#60a5fa);
  min-width:2px;transition:width .4s}
.ffill.green{background:linear-gradient(90deg,#10B981,#34d399)}
.ffill.grey{background:linear-gradient(90deg,#94a3b8,#cbd5e1)}
.frow .fn{font-size:.82rem;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
.frow .fn small{display:block;font-weight:500;color:var(--muted);font-size:.7rem}
/* tables */
table{border-collapse:collapse;width:100%;font-size:.85rem}
th{text-align:left;font-size:.72rem;font-weight:700;letter-spacing:.04em;text-transform:uppercase;
  color:var(--muted);padding:.5rem .65rem;border-bottom:1px solid var(--line)}
td{padding:.6rem .65rem;border-bottom:1px solid var(--line);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr.clk:hover{background:var(--bg);cursor:pointer}
.num{text-align:right;font-variant-numeric:tabular-nums}
/* badges */
.badge{display:inline-flex;align-items:center;font-size:.72rem;font-weight:700;padding:.22rem .6rem;border-radius:var(--radius-pill);white-space:nowrap}
.b-success{background:rgba(16,185,129,.12);color:#0f9d6c}
.b-info{background:rgba(139,92,246,.12);color:#7c3aed}
.b-warning{background:rgba(245,158,11,.14);color:#b45309}
.b-error{background:rgba(220,38,38,.1);color:#dc2626}
.b-muted{background:rgba(15,23,42,.06);color:var(--muted)}
.b-neutral{background:rgba(59,130,246,.1);color:var(--action)}
/* chips */
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1.1rem}
.chip{font-size:.78rem;font-weight:600;padding:.35rem .8rem;border-radius:var(--radius-pill);
  background:var(--white);border:1px solid var(--line);color:var(--muted)}
.chip.active{background:var(--brand);color:#fff;border-color:var(--brand)}
.chip b{margin-left:.35rem;opacity:.7}
/* cards (queue) */
.qcard{background:var(--white);border-radius:var(--radius-card);box-shadow:var(--shadow-sm);
  border:1px solid var(--line);padding:1.15rem 1.3rem;margin-bottom:.9rem;display:flex;
  align-items:center;justify-content:space-between;gap:1rem}
.qcard .who b{font-size:.95rem} .qcard .who .m{font-size:.78rem;color:var(--muted)}
/* forms */
textarea{width:100%;min-height:13rem;font:13.5px/1.6 var(--mono);padding:.8rem;border:1px solid var(--line);
  border-radius:var(--radius-input);background:#fcfcfd;resize:vertical}
input[type=text],input:not([type]){padding:.5rem .7rem;border:1px solid var(--line);border-radius:var(--radius-input);font:inherit;font-size:.85rem;min-width:220px}
label.fld{display:block;font-size:.78rem;font-weight:600;color:var(--muted);margin:.9rem 0 .35rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;font:inherit;font-size:.85rem;font-weight:600;
  border:none;border-radius:var(--radius-pill);padding:.6rem 1.4rem;cursor:pointer;transition:all .15s}
.btn-primary{background:var(--action);color:#fff;box-shadow:0 2px 8px rgba(59,130,246,.25)}
.btn-primary:hover{background:var(--action-hover);transform:translateY(-1px)}
.btn-ghost{background:var(--white);color:var(--brand);border:1.5px solid var(--line)}
.btn-ghost:hover{border-color:rgba(15,23,42,.3)}
.row{display:flex;gap:.75rem;align-items:flex-end;flex-wrap:wrap}
.alert{background:rgba(220,38,38,.08);color:#b91c1c;border:1px solid rgba(220,38,38,.2);
  padding:.7rem .9rem;border-radius:var(--radius-input);font-size:.84rem;margin-bottom:1rem}
.note{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);color:#92400e;
  padding:.75rem 1rem;border-radius:var(--radius-input);font-size:.82rem;margin-bottom:1.5rem}
.two{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}
.kv{display:grid;grid-template-columns:150px 1fr;gap:.4rem .8rem;font-size:.85rem}
.kv dt{color:var(--muted);font-weight:600} .kv dd{font-weight:500}
.body-box{font:13.5px/1.65 var(--mono);background:#fcfcfd;border:1px solid var(--line);
  border-radius:var(--radius-input);padding:1rem;white-space:pre-wrap}
.feed{display:flex;flex-direction:column}
.feed .ev{display:flex;gap:.8rem;padding:.55rem 0;border-bottom:1px solid var(--line);font-size:.82rem;align-items:baseline}
.feed .ev:last-child{border-bottom:none}
.feed .t{color:var(--muted);font-size:.72rem;white-space:nowrap;min-width:118px}
.feed .r{color:var(--muted)}
.muted{color:var(--muted)} .empty{color:var(--muted);font-size:.88rem;padding:1.5rem 0;text-align:center}
@media(max-width:820px){.sidebar{display:none}.two{grid-template-columns:1fr}.frow{grid-template-columns:120px 1fr 70px}}
"""


def _icon(name: str) -> str:
    raw = ICONS.get(name, "")
    if not raw:
        return ""
    # an ICONS value may hold several subpaths separated by " M"; restore each M
    parts = raw.split(" M")
    subpaths = [parts[0]] + ["M" + p for p in parts[1:]]
    paths = "".join(
        f'<path stroke-linecap="round" stroke-linejoin="round" d="{d}"/>' for d in subpaths)
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">{paths}</svg>'


def _badge(state: str) -> str:
    label, kind = STATE_STYLE.get(state, (state, "neutral"))
    return f'<span class="badge b-{kind}">{html.escape(label)}</span>'


def _pct(n: int, d: int) -> float:
    return (100.0 * n / d) if d else 0.0


def _safety() -> dict:
    return {
        "live": config.send_enabled(),
        "kill": bool(config.KILL_SWITCH),
        "cap": config.PER_INBOX_DAILY_CAP,
        "resolver": config.WEBSITE_RESOLVER,
        "sender": config.GRAPH_SENDER or "(not configured)",
        "accept_catch_all": config.ACCEPT_CATCH_ALL,
        "risky_send": config.RISKY_SEND_ENABLED,
    }


def _shell(active: str, title: str, sub: str, body: str) -> str:
    s = _safety()
    nav = ""
    for href, label, icon in NAV:
        cls = "active" if href == active else ""
        nav += f'<a class="{cls}" href="{href}">{_icon(icon)}<span>{label}</span></a>'
    nav += f'<a class="soon">{_icon("inbox")}<span>Sequences</span><span class="tag">Soon</span></a>'
    if s["live"]:
        send_line = '<span class="dot dot-red"></span>LIVE SEND ENABLED'
    elif s["kill"]:
        send_line = '<span class="dot dot-red"></span>Kill switch ON'
    else:
        send_line = '<span class="dot dot-amber"></span>Dry-run · G-SEND off'
    pill = ('<span class="statpill" style="background:rgba(220,38,38,.1);color:#dc2626">'
            '<span class="dot" style="background:#dc2626"></span>LIVE SEND</span>') if s["live"] else (
            '<span class="statpill"><span class="dot"></span>Dry-run mode · G-SEND off</span>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · SettlePay Outreach</title>
<link rel="preconnect" href="https://api.fontshare.com" crossorigin>
<link rel="preconnect" href="https://cdn.fontshare.com" crossorigin>
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap">
<style>{_STYLE}</style></head><body><div class="app">
<aside class="sidebar">
  <div class="brand"><b>SettlePay</b><span>Outreach</span></div>
  <nav class="nav">{nav}</nav>
  <div class="side-status">{send_line}<br>
    <span class="muted" style="color:rgba(255,255,255,.45);font-size:.7rem">
    Resolver: {html.escape(s['resolver'])} · Cap {s['cap']}/inbox/day</span></div>
</aside>
<main class="main">
  <div class="topbar"><div><h1>{html.escape(title)}</h1><div class="sub">{sub}</div></div>{pill}</div>
  <div class="content">{body}</div>
</main></div></body></html>"""


# --------------------------------------------------------------------------- #
#  Dashboard
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/dashboard", status_code=307)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    with db.cursor(commit=False) as cur:
        o = stats.overview(cur)
        verify = stats.verify_breakdown(cur)
        verticals = stats.by_vertical(cur)
        effort = stats.scrape_effort(cur)
        feed = stats.recent_activity(cur)
    g = graduation_thresholds()

    tiles = [
        ("accent", o["discovered"], "Companies discovered", "Companies House"),
        ("", o["corporate"], "PECR-cleared", f"{o['suppressed']} suppressed"),
        ("", o["emails_verified"], "Verified emails", f"+{o['emails_risky']} risky · {o['emails_found']} found"),
        ("", o["drafts_awaiting"], "Awaiting approval", "in your queue"),
        ("", o["approved"], "Approved", f"{o['unedited_rate']:.0%} unedited"),
        ("", o["sends_dry"], "Dry-run sends", f"{o['sends_live']} live"),
    ]
    kpis = "".join(
        f'<div class="tile {cls}"><div class="n">{n}</div><div class="l">{l}</div><div class="s">{s}</div></div>'
        for cls, n, l, s in tiles)

    disc = o["discovered"] or 1
    stages = [
        ("Discovered", o["discovered"], "blue"),
        ("PECR-cleared", o["corporate"], "blue"),
        ("Website resolved", o["websites"], "blue"),
        ("Email found", o["emails_found"], "blue"),
        ("Email verified", o["emails_verified"], "green"),
        ("Drafted", o["drafts_total"], "blue"),
        ("Approved", o["approved"], "green"),
        ("Sent (dry-run)", o["sends_dry"], "grey"),
    ]
    funnel = ""
    for label, n, colour in stages:
        w = _pct(n, disc)
        cl = {"blue": "", "green": "green", "grey": "grey"}[colour]
        funnel += (f'<div class="frow"><div class="fl">{label}</div>'
                   f'<div class="ftrack"><div class="ffill {cl}" style="width:{max(w,1):.1f}%"></div></div>'
                   f'<div class="fn">{n}<small>{w:.0f}% of disc.</small></div></div>')

    vrows = "".join(
        f'<tr class="clk" onclick="location.href=\'/leads?vertical={html.escape(v["sic"])}\'">'
        f'<td><b>{html.escape(v["label"])}</b><br><span class="muted" style="font-size:.74rem">SIC {html.escape(v["sic"])}</span></td>'
        f'<td class="num">{v["total"]}</td><td class="num">{v["corporate"]}</td>'
        f'<td class="num">{v["websites"]}</td><td class="num">{v["emails"]}</td>'
        f'<td class="num">{v["verified"]}</td><td class="num">{v["yield"]:.0%}</td></tr>'
        for v in verticals) or '<tr><td colspan=7 class="empty">No leads yet.</td></tr>'

    vbreak = "".join(
        f'<tr><td>{html.escape(r[0])}</td><td class="num">{r[1]}</td></tr>' for r in verify
    ) or '<tr><td colspan=2 class="empty">No verifications yet.</td></tr>'

    feed_html = "".join(
        f'<div class="ev"><span class="t">{c.strftime("%d %b %H:%M") if c else ""}</span>'
        f'{_badge_event(ev)}<span>{html.escape(name or cn or "")}</span>'
        f'<span class="r">— {html.escape((reason or "")[:90])}</span></div>'
        for c, ev, cn, name, reason in feed) or '<div class="empty">No activity yet.</div>'

    grad = (f'<table><tr><th>Metric</th><th class="num">Now</th><th class="num">Target</th></tr>'
            f'<tr><td>Reviewed drafts (per vertical)</td><td class="num">{o["drafts_total"]}</td>'
            f'<td class="num muted">&ge; {g.get("min_reviewed_drafts_per_vertical","?")}</td></tr>'
            f'<tr><td>Approved-unedited rate</td><td class="num">{o["unedited_rate"]:.0%}</td>'
            f'<td class="num muted">&ge; {g.get("min_approved_unedited_rate",0):.0%}</td></tr>'
            f'<tr><td>Bounce rate</td><td class="num muted">n/a</td>'
            f'<td class="num muted">&lt; {g.get("max_bounce_rate",0):.0%}</td></tr></table>')

    effort_line = (f'<b>{o["websites"]}</b> sites with a resolved URL · contact found by: '
                   f'<b>{effort["guess"]}</b> info@ guess, <b>{effort["httpx"]}</b> httpx scrape, '
                   f'<b>{effort["firecrawl"]}</b> Firecrawl · '
                   f'<b>{effort["emails_found_total"]}</b> candidate emails harvested'
                   if effort["tracked"] else
                   f'<b>{o["websites"]}</b> sites fetched (info@ guess-and-verify, then httpx, then Firecrawl). '
                   f'<span class="muted">Source split tracked from this build onward.</span>')

    body = f"""
{'<div class="note">Live sending is OFF. The pipeline is in dry-run; nothing leaves an inbox until a human sets the G-SEND gate.</div>' if not _safety()['live'] else ''}
<div class="kpis">{kpis}</div>
<div class="panel"><h2>Conversion funnel</h2>
  <div class="hint">Every stage as a share of companies discovered. This is where the system wins and leaks.</div>
  <div class="funnel">{funnel}</div>
  <div style="margin-top:1.1rem;font-size:.83rem" class="muted">{effort_line}</div>
</div>
<div class="two">
  <div class="panel"><h2>Yield by vertical</h2>
    <div class="hint">Which lead source actually produces contactable companies. Click a row to filter.</div>
    <table><tr><th>Vertical</th><th class="num">Leads</th><th class="num">Corp.</th><th class="num">Sites</th>
    <th class="num">Emails</th><th class="num">Verified</th><th class="num">Yield</th></tr>{vrows}</table>
  </div>
  <div class="panel"><h2>Email verification</h2>
    <div class="hint">MillionVerifier outcome distribution — the biggest contactability filter.</div>
    <table><tr><th>Result</th><th class="num">Count</th></tr>{vbreak}</table>
  </div>
</div>
<div class="two">
  <div class="panel"><h2>Graduation to auto-send</h2>
    <div class="hint">Thresholds a vertical must clear before any unattended sending is considered (policy).</div>
    {grad}</div>
  <div class="panel"><h2>Compliance &amp; safety</h2>
    <div class="hint">PECR firewall + send gating, live.</div>
    <dl class="kv">
      <dt>PECR suppressed</dt><dd>{o['suppressed']} (individual / unknown subscribers)</dd>
      <dt>Discarded</dt><dd>{o['discarded']} (no verifiable contact)</dd>
      <dt>Live sends</dt><dd>{o['sends_live']} &nbsp;<span class="badge b-{'error' if _safety()['live'] else 'success'}">{'ENABLED' if _safety()['live'] else 'gated (G-SEND off)'}</span></dd>
      <dt>Per-inbox cap</dt><dd>{_safety()['cap']} / day</dd>
    </dl></div>
</div>
<div class="panel"><h2>Recent activity</h2>
  <div class="hint">Audit trail — one row per lead decision, each carrying its lawful basis.</div>
  <div class="feed">{feed_html}</div>
</div>"""
    return _shell("/dashboard", "Dashboard", "Live overview of the outreach pipeline", body)


def _badge_event(ev: str) -> str:
    m = {"discovered": "neutral", "classified": "neutral", "enriched": "info",
         "drafted": "info", "approved": "success", "rejected": "error",
         "suppressed": "muted", "discarded": "muted", "dry_run_send": "neutral"}
    return f'<span class="badge b-{m.get(ev,"neutral")}">{html.escape(ev)}</span>'


# --------------------------------------------------------------------------- #
#  Approval queue
# --------------------------------------------------------------------------- #
@app.get("/queue", response_class=HTMLResponse)
def queue():
    with db.cursor(commit=False) as cur:
        rows = review.list_pending(cur)
        sigs = {}
        if rows:
            cns = tuple(r[1] for r in rows)
            cur.execute("select company_number, signal from outreach.enrichment "
                        "where company_number = any(%s)", (list(cns),))
            sigs = dict(cur.fetchall())
    cards = "".join(
        f'<div class="qcard"><div class="who"><b>{html.escape(name)}</b> '
        f'<span class="m">({html.escape(cn)})</span><br>'
        f'<span class="m">{html.escape((sigs.get(cn) or "no signal on file")[:80])}</span></div>'
        f'<a class="btn btn-primary" href="/draft/{did}">Review &rarr;</a></div>'
        for did, cn, name, _body in rows
    ) or '<div class="panel"><div class="empty">Nothing awaiting approval. Drafts will appear here once leads are enriched and drafted.</div></div>'
    head = f'<div class="panel"><h2>{len(rows)} draft{"" if len(rows)==1 else "s"} awaiting your decision</h2>' \
           f'<div class="hint">Approving advances a draft to <b>approved</b> only — sending stays gated behind G-SEND.</div></div>'
    return _shell("/queue", "Approval queue", "The human gate before any send", head + cards)


@app.get("/draft/{draft_id}", response_class=HTMLResponse)
def draft_view(draft_id: str, err: str = ""):
    with db.cursor(commit=False) as cur:
        cur.execute(
            "select d.company_number, l.company_name, d.body_original, d.status, "
            "e.contact_email, e.email_verify_result, e.website, e.signal "
            "from outreach.drafts d join outreach.leads l on l.company_number=d.company_number "
            "left join outreach.enrichment e on e.company_number=d.company_number "
            "where d.id=%s", (draft_id,))
        row = cur.fetchone()
    if not row:
        return HTMLResponse(_shell("/queue", "Not found", "", '<div class="panel"><div class="empty">Draft not found.</div></div>'), status_code=404)
    cn, name, body, status, email, vres, website, signal = row
    errhtml = f'<div class="alert">{html.escape(err)}</div>' if err else ""
    site = f'<a href="{html.escape(website)}" target="_blank">{html.escape(website)}</a>' if website else "—"
    body_html = f"""
{errhtml}
<div class="two">
  <div class="panel"><h2>Draft message</h2>
    <div class="hint">body_original is immutable. Edit below to approve a revised version (compliance is re-checked on save).</div>
    <form method="post" action="/approve/{draft_id}">
      <textarea name="edited">{html.escape(body)}</textarea>
      <div class="row">
        <div><label class="fld">Reviewer</label><input name="reviewer" required placeholder="Your name"></div>
        <div style="flex:1"><label class="fld">Note (optional)</label><input name="note" style="width:100%"></div>
      </div>
      <div class="row" style="margin-top:1rem"><button class="btn btn-primary" type="submit">Approve</button></div>
    </form>
    <form method="post" action="/reject/{draft_id}" style="margin-top:1.25rem;border-top:1px solid var(--line);padding-top:1.1rem">
      <div class="row"><div><label class="fld">Reviewer</label><input name="reviewer" required placeholder="Your name"></div>
      <div style="flex:1"><label class="fld">Reason (optional)</label><input name="note" style="width:100%"></div>
      <button class="btn btn-ghost" type="submit">Reject</button></div>
    </form>
  </div>
  <div class="panel"><h2>Lead context</h2>
    <dl class="kv">
      <dt>Company</dt><dd>{html.escape(name)}</dd>
      <dt>Number</dt><dd>{html.escape(cn)}</dd>
      <dt>Status</dt><dd>{_badge(status if status in STATE_STYLE else 'drafted')}</dd>
      <dt>Contact</dt><dd>{html.escape(email or '—')}</dd>
      <dt>Verify</dt><dd>{html.escape(vres or '—')}</dd>
      <dt>Website</dt><dd>{site}</dd>
      <dt>Signal</dt><dd>{html.escape(signal or '—')}</dd>
    </dl>
    <p class="muted" style="margin-top:1rem;font-size:.8rem"><a href="/lead/{html.escape(cn)}">Full lead record &rarr;</a></p>
  </div>
</div>"""
    return _shell("/queue", f"Review · {name}", "Approve, edit, or reject this draft", body_html)


@app.post("/approve/{draft_id}")
def approve(draft_id: str, reviewer: str = Form(...), edited: str = Form(""), note: str = Form("")):
    try:
        with db.cursor(commit=False) as cur:
            cur.execute("select body_original from outreach.drafts where id=%s", (draft_id,))
            r = cur.fetchone()
        original = (r[0] if r else "") or ""
        edit_arg = None if edited.strip() == original.strip() else edited
        review.approve(draft_id, reviewer, edited=edit_arg, note=note or None)
    except Exception as e:
        return RedirectResponse(f"/draft/{draft_id}?err={html.escape(str(e))}", status_code=303)
    return RedirectResponse("/queue", status_code=303)


@app.post("/reject/{draft_id}")
def reject(draft_id: str, reviewer: str = Form(...), note: str = Form("")):
    try:
        review.reject(draft_id, reviewer, note=note or None)
    except Exception as e:
        return RedirectResponse(f"/draft/{draft_id}?err={html.escape(str(e))}", status_code=303)
    return RedirectResponse("/queue", status_code=303)


# --------------------------------------------------------------------------- #
#  Leads (CRM)
# --------------------------------------------------------------------------- #
@app.get("/leads", response_class=HTMLResponse)
def leads(state: str = "", vertical: str = ""):
    where, params = [], []
    if state:
        where.append("l.state = %s")
        params.append(state)
    if vertical:
        where.append("l.sic_codes[1] = %s")
        params.append(vertical)
    clause = ("where " + " and ".join(where)) if where else ""
    with db.cursor(commit=False) as cur:
        cur.execute("select state::text, count(*) from outreach.leads group by 1", ())
        counts = dict(cur.fetchall())
        cur.execute(
            "select l.company_number, l.company_name, l.sic_codes[1], l.state::text, "
            "e.website, e.contact_email, e.email_verified "
            f"from outreach.leads l left join outreach.enrichment e on e.company_number=l.company_number "
            f"{clause} order by l.updated_at desc limit 500", tuple(params))
        rows = cur.fetchall()

    total = sum(counts.values())
    chips = f'<a class="chip {"active" if not state else ""}" href="/leads">All <b>{total}</b></a>'
    for st in ["awaiting_approval", "approved", "drafted", "enriched", "discovered", "suppressed", "discarded", "rejected"]:
        if counts.get(st):
            chips += f'<a class="chip {"active" if state==st else ""}" href="/leads?state={st}">{STATE_STYLE.get(st,(st,))[0]} <b>{counts[st]}</b></a>'

    trs = ""
    for cn, name, sic, st, website, email, verified in rows:
        site = f'<a href="{html.escape(website)}" target="_blank" onclick="event.stopPropagation()">{html.escape(_short(website))}</a>' if website else '<span class="muted">—</span>'
        vmark = '<span class="badge b-success">✓</span>' if verified else ('<span class="muted">—</span>')
        trs += (f'<tr class="clk" onclick="location.href=\'/lead/{html.escape(cn)}\'">'
                f'<td><b>{html.escape(name)}</b><br><span class="muted" style="font-size:.74rem">{html.escape(cn)}</span></td>'
                f'<td>{html.escape(stats.sic_label(sic))}</td><td>{_badge(st)}</td>'
                f'<td>{site}</td><td>{html.escape(email or "")}</td><td class="num">{vmark}</td></tr>')
    if not trs:
        trs = '<tr><td colspan=6 class="empty">No leads match this filter.</td></tr>'
    body = f"""<div class="chips">{chips}</div>
<div class="panel"><table>
<tr><th>Company</th><th>Vertical</th><th>State</th><th>Website</th><th>Contact email</th><th class="num">Verified</th></tr>
{trs}</table>
<p class="muted" style="margin-top:1rem;font-size:.78rem">Showing {len(rows)} lead(s){' (capped at 500)' if len(rows)==500 else ''}.</p>
</div>"""
    return _shell("/leads", "Leads", "CRM view of every discovered company", body)


def _short(url: str) -> str:
    import re as _re
    return _re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")[:38]


@app.get("/lead/{company_number}", response_class=HTMLResponse)
def lead_detail(company_number: str):
    with db.cursor(commit=False) as cur:
        cur.execute(
            "select company_name, company_number, company_type, company_status, "
            "sic_codes, subscriber_class::text, state::text, registered_address "
            "from outreach.leads where company_number=%s", (company_number,))
        lead = cur.fetchone()
        if not lead:
            return HTMLResponse(_shell("/leads", "Not found", "", '<div class="panel"><div class="empty">Lead not found.</div></div>'), status_code=404)
        cur.execute(
            "select website, contact_email, email_verified, email_verify_result, signal, scraped, contact_tier "
            "from outreach.enrichment where company_number=%s", (company_number,))
        enr = cur.fetchone()
        cur.execute(
            "select id, status, body_original, body_final, decided_by, decided_at "
            "from outreach.drafts where company_number=%s order by created_at desc", (company_number,))
        drafts = cur.fetchall()
        cur.execute(
            "select created_at, event, reason from outreach.audit_log "
            "where company_number=%s order by created_at", (company_number,))
        audit_rows = cur.fetchall()

    name, cn, ctype, cstatus, sics, scls, state, addr = lead
    locality = (addr or {}).get("locality") or (addr or {}).get("region") or ""
    facts = f"""<dl class="kv">
      <dt>State</dt><dd>{_badge(state)}</dd>
      <dt>Subscriber</dt><dd>{html.escape(scls or '—')}</dd>
      <dt>Company type</dt><dd>{html.escape(ctype or '—')}</dd>
      <dt>CH status</dt><dd>{html.escape(cstatus or '—')}</dd>
      <dt>SIC</dt><dd>{html.escape(", ".join(sics or []) or '—')}</dd>
      <dt>Location</dt><dd>{html.escape(locality or '—')}</dd></dl>"""

    if enr:
        website, email, verified, vres, signal, scraped, tier = enr
        site = f'<a href="{html.escape(website)}" target="_blank">{html.escape(website)}</a>' if website else '—'
        cands = ", ".join((scraped or {}).get("candidates", [])) if scraped else ""
        src = (scraped or {}).get("source") if scraped else None
        tier_badge = {"verified": '<span class="badge b-success">verified</span>',
                      "risky": '<span class="badge b-warning">risky · catch-all</span>'}.get(
                          tier, '<span class="badge b-muted">—</span>')
        enr_html = f"""<dl class="kv">
          <dt>Website</dt><dd>{site}</dd>
          <dt>Contact</dt><dd>{html.escape(email or '—')}</dd>
          <dt>Contact tier</dt><dd>{tier_badge} <span class="muted">({html.escape(vres or 'n/a')})</span></dd>
          <dt>Scraper</dt><dd>{html.escape(src or '—')}</dd>
          <dt>Candidates</dt><dd>{html.escape(cands or '—')}</dd>
          <dt>Signal</dt><dd>{html.escape(signal or '—')}</dd></dl>"""
    else:
        enr_html = '<div class="empty">Not enriched.</div>'

    draft_html = ""
    for did, dstatus, bo, bf, by, at in drafts:
        edited = bf and bf.strip() != (bo or "").strip()
        meta = f'{html.escape(dstatus)}' + (f' · {html.escape(by)}' if by else '') + (' · edited' if edited else '')
        shown = bf if (bf and dstatus != 'awaiting_approval') else bo
        draft_html += (f'<div style="margin-bottom:1rem"><div class="muted" style="font-size:.78rem;margin-bottom:.4rem">'
                       f'{meta}</div><div class="body-box">{html.escape(shown or "")}</div></div>')
    draft_html = draft_html or '<div class="empty">No drafts yet.</div>'

    feed = "".join(
        f'<div class="ev"><span class="t">{c.strftime("%d %b %H:%M") if c else ""}</span>'
        f'{_badge_event(ev)}<span class="r">{html.escape((reason or "")[:110])}</span></div>'
        for c, ev, reason in audit_rows) or '<div class="empty">No audit events.</div>'

    body = f"""
<div class="two">
  <div class="panel"><h2>{html.escape(name)}</h2><div class="hint">{html.escape(cn)}</div>{facts}</div>
  <div class="panel"><h2>Enrichment</h2><div class="hint">Discovery → scrape → verify</div>{enr_html}</div>
</div>
<div class="panel"><h2>Drafts</h2>{draft_html}</div>
<div class="panel"><h2>Audit timeline</h2><div class="feed">{feed}</div></div>
<p class="muted" style="font-size:.8rem"><a href="/leads">&larr; Back to leads</a></p>"""
    return _shell("/leads", name, "Lead record", body)


# --------------------------------------------------------------------------- #
#  Settings (read-only runtime posture)
# --------------------------------------------------------------------------- #
@app.get("/settings", response_class=HTMLResponse)
def settings():
    s = _safety()
    try:
        seq = load_sequence_config()
    except Exception:
        seq = {}
    win = seq.get("send_window", {})
    cfg = f"""<div class="two">
  <div class="panel"><h2>Send safety</h2>
    <div class="hint">The gates that keep this from emailing anyone before you're ready.</div>
    <dl class="kv">
      <dt>Live send (G-SEND)</dt><dd>{'<span class="badge b-error">ENABLED</span>' if s['live'] else '<span class="badge b-success">gated — off</span>'}</dd>
      <dt>Kill switch</dt><dd>{'<span class="badge b-error">ON (all sends blocked)</span>' if s['kill'] else '<span class="badge b-muted">off</span>'}</dd>
      <dt>Per-inbox cap</dt><dd>{s['cap']} / day</dd>
      <dt>Risky (catch-all) send</dt><dd>{'<span class="badge b-error">ENABLED</span>' if s['risky_send'] else '<span class="badge b-success">off — needs RISKY_SEND_ENABLED</span>'}</dd>
      <dt>Sending domain</dt><dd>{html.escape(s['sender'])}</dd>
      <dt>Send window</dt><dd>{win.get('start_hour','?')}:00–{win.get('end_hour','?')}:00 <span class="muted">(placeholder)</span></dd>
    </dl></div>
  <div class="panel"><h2>Pipeline config</h2>
    <div class="hint">From outreach/.env — secrets never shown.</div>
    <dl class="kv">
      <dt>DB schema</dt><dd>{html.escape(config.DB_SCHEMA)}</dd>
      <dt>Enquiry source</dt><dd>public.{html.escape(config.ENQUIRY_SOURCE_TABLE)} <span class="muted">(suppression)</span></dd>
      <dt>Website resolver</dt><dd>{html.escape(s['resolver'])}</dd>
      <dt>Catch-all policy</dt><dd>{'accept as risky tier' if s['accept_catch_all'] else 'discard'}</dd>
      <dt>LLM provider</dt><dd>{html.escape(config.LLM_PROVIDER)}</dd>
      <dt>CH cap</dt><dd>{config.CH_MAX_REQUESTS_PER_RUN} req/run</dd>
      <dt>Verify cap</dt><dd>{config.MV_MAX_PER_RUN}/run</dd>
      <dt>Search cap</dt><dd>{config.SEARCH_MAX_REQUESTS_PER_RUN}/run</dd>
    </dl></div>
</div>
<div class="note">This is a read-only view. Changing any of these means editing <b>outreach/.env</b> (or
<b>sequence_config.json</b>) and restarting the service — deliberately not editable from the browser, since
this console has no authentication.</div>"""
    return _shell("/settings", "Settings", "Runtime configuration & safety posture (read-only)", cfg)
