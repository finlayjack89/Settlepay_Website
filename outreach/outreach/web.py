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
    # then open http://localhost:8787/
"""
from __future__ import annotations
import html
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import config, db, enquiries, graduation, jobs, monitor, outbox, research
from . import review, stats, webauth
# aliased: this module defines a `schedule()` route that would shadow the import
from . import schedule as send_queue
from . import tasks as _tasks  # noqa: F401 — importing populates jobs.REGISTRY
from .sequence import graduation_thresholds, load_sequence_config

app = FastAPI(title="SettlePay — operations console")
# All console routes live on this router, mounted under BASE_PATH ("" locally,
# "/dashboard" when proxied at settlepay.uk/dashboard via the Vercel rewrite).
router = APIRouter()


def u(path: str) -> str:
    """Prefix an absolute console path with BASE_PATH (redirects/links)."""
    return f"{config.BASE_PATH}{path}"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else None) or \
        (request.client.host if request.client else "unknown")


_login_limiter = webauth.LoginRateLimiter()


def _session_token(request: Request):
    return request.cookies.get(webauth.COOKIE_NAME)


def _csrf_field(request: Request) -> str:
    """Hidden CSRF input for authed POST forms ('' in open/local mode)."""
    tok = _session_token(request)
    if not (webauth.auth_configured() and tok):
        return ""
    return f'<input type="hidden" name="csrf" value="{webauth.csrf_token(tok)}">'


def _csrf_ok(request: Request, provided: str) -> bool:
    if not webauth.auth_configured():
        return True
    return webauth.verify_csrf(_session_token(request), provided)


_CSRF_DENIED = HTMLResponse("<h3>Forbidden: bad or missing CSRF token.</h3>", status_code=403)


@app.middleware("http")
async def _auth_gate(request: Request, call_next):
    """Session gate for every console route. OPEN when auth is not configured
    (local dev — see webauth docstring); /healthz and /tick verify themselves."""
    path = request.url.path
    exempt = (path in ("/healthz", "/tick")
              or path == u("/healthz")
              or path == u("/login")
              or path.startswith(u("/integrations/")))
    if not webauth.auth_configured() or exempt \
            or webauth.verify_session(_session_token(request)):
        return await call_next(request)
    return RedirectResponse(u("/login"), status_code=303)


@app.on_event("startup")
def _start_jobs_runner():
    """Recover jobs orphaned by a restart and start the single worker. Skipped
    cleanly when the DB is unreachable so the app can still boot and show that."""
    try:
        jobs.recover_stale()
        app.state.job_runner = jobs.JobRunner()
        app.state.job_runner.start()
    except Exception:
        app.state.job_runner = None
    # separate from the job runner on purpose: the outbox undo window is measured in
    # seconds, and it must not queue behind a task that runs for minutes
    try:
        app.state.outbox_sweeper = outbox.OutboxSweeper()
        app.state.outbox_sweeper.start()
    except Exception:
        app.state.outbox_sweeper = None


@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True})


# run.app's Google frontend intercepts root /healthz before it reaches the
# container, so health must also be reachable under BASE_PATH (which is all the
# settlepay.uk proxy forwards anyway).
if config.BASE_PATH:
    app.add_api_route(u("/healthz"), healthz, methods=["GET"])


@app.post("/tick")
def tick_endpoint(request: Request):
    """Cloud Scheduler entrypoint: enqueue ONE tick job (deduped) and return.
    OIDC-verified in production; open only in unconfigured local dev."""
    if webauth.auth_configured() and not webauth.verify_tick_request(
            request.headers.get("authorization")):
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    job_id = jobs.enqueue("tick", {"dry_run": not config.send_enabled()},
                          requested_by="scheduler", dedupe=True)
    return JSONResponse({"job_id": job_id})

# Grouped sidebar: one unified surface over inbound (enquiries) + outbound (outreach).
NAV_GROUPS = [
    (None, [("/", "Dashboard", "grid")]),
    ("Inbound", [
        ("/enquiries", "Enquiries", "inbox"),
        ("/schedule", "Schedule", "calendar"),
    ]),
    ("Outbound", [
        ("/outreach", "Outreach", "megaphone"),
        ("/outreach/queue", "Approval queue", "clipboard"),
        ("/outreach/sending", "Sending", "send"),
        ("/outreach/leads", "Leads", "users"),
        ("/research", "Research", "search"),
        ("/intelligence", "Intelligence", "chart"),
    ]),
    ("Operate", [
        ("/tasks", "Launch", "play"),
        ("/jobs", "Jobs", "list"),
    ]),
    ("System", [("/settings", "Settings", "cog")]),
]

ICONS = {
    "grid": "M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z",
    "inbox": "M2.25 13.5h3.86a2.25 2.25 0 012.012 1.244l.256.512a2.25 2.25 0 002.013 1.244h3.218a2.25 2.25 0 002.013-1.244l.256-.512a2.25 2.25 0 012.013-1.244h3.859m-19.5.338V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18v-4.162c0-.224-.034-.447-.1-.661L19.24 5.338a2.25 2.25 0 00-2.15-1.588H6.911a2.25 2.25 0 00-2.15 1.588L2.35 13.177a2.25 2.25 0 00-.1.661z",
    "calendar": "M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5",
    "chart": "M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0020.25 18V6A2.25 2.25 0 0018 3.75H6A2.25 2.25 0 003.75 6v12A2.25 2.25 0 006 20.25z",
    "megaphone": "M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 110-9h.75c.704 0 1.402-.03 2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.55.06 1.21-.463 1.511l-.657.38c-.551.318-1.26.117-1.527-.461a20.845 20.845 0 01-1.44-4.282m3.102.069a18.03 18.03 0 01-.59-4.59c0-1.586.205-3.124.59-4.59m0 9.18a23.848 23.848 0 018.835 2.535M10.34 6.66a23.847 23.847 0 008.835-2.535",
    "clipboard": "M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 002.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 00-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 00.75-.75 2.25 2.25 0 00-.1-.664m-5.8 0A2.251 2.251 0 0113.5 2.25H15c1.012 0 1.867.668 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25z",
    "users": "M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z",
    "play": "M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z",
    "list": "M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zM3.75 12h.007v.008H3.75V12zm0 5.25h.007v.008H3.75v-.008z",
    "send": "M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5",
    "search": "M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z",
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

# inbound enquiry status -> (label, semantic colour key)
ENQUIRY_STYLE = {
    "new": ("New", "warning"),
    "contacted": ("Contacted", "neutral"),
    "quoted": ("Quoted", "info"),
    "won": ("Won", "success"),
    "client": ("Client", "success"),
    "lost": ("Lost", "muted"),
}
PIPELINE_ORDER = ["new", "contacted", "quoted", "won", "client", "lost"]


def _enq_badge(status: str) -> str:
    label, kind = ENQUIRY_STYLE.get(status, (status, "neutral"))
    return f'<span class="badge b-{kind}">{html.escape(label)}</span>'


def _ago(dt) -> str:
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


_UK = ZoneInfo("Europe/London")
# booking status -> (label, semantic colour key)
_BOOKING_STYLE = {
    "confirmed": ("Confirmed", "success"),
    "rescheduled": ("Rescheduled", "info"),
    "cancelled": ("Cancelled", "muted"),
}


def _booking_badge(status: str) -> str:
    label, kind = _BOOKING_STYLE.get(status, (status, "neutral"))
    return f'<span class="badge b-{kind}">{html.escape(label)}</span>'


def _when(dt) -> str:
    """Format a booking time in UK local time, e.g. 'Tue 01 Jul · 14:00'."""
    if not dt:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_UK).strftime("%a %d %b · %H:%M")


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
.nav-group{font-size:.62rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:rgba(255,255,255,.3);padding:.9rem .75rem .25rem}
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
.ffill.amber{background:linear-gradient(90deg,#F59E0B,#fbbf24)}
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
input[type=text],input:not([type]),select{padding:.5rem .7rem;border:1px solid var(--line);border-radius:var(--radius-input);font:inherit;font-size:.85rem;min-width:220px;background:#fff}
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
.ok{background:rgba(16,185,129,.1);border:1px solid rgba(16,185,129,.25);color:#0f7a55;
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
.obrow{display:flex;align-items:center;gap:1rem;padding:.7rem 0;border-top:1px solid var(--line)}
.obrow>div:first-child{flex:1}
.obcount{font-variant-numeric:tabular-nums;font-weight:600;color:#b45309;min-width:4.5rem;text-align:right}
.tags{display:flex;flex-wrap:wrap;gap:.35rem;margin:.3rem 0 .1rem}
.tag{background:var(--wash,#f1f5f9);border-radius:100px;padding:.16rem .6rem;font-size:.76rem}
.hooks{margin:.4rem 0 0;padding-left:1.1rem} .hooks li{margin:.3rem 0;font-size:.88rem}
.quote{border-left:2px solid var(--line);padding-left:.7rem;margin:.35rem 0;font-size:.8rem;color:var(--muted)}
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
        "sender": config.GMAIL_SENDER or "(not configured)",
        "accept_catch_all": config.ACCEPT_CATCH_ALL,
        "risky_send": config.RISKY_SEND_ENABLED,
    }


def _prefix_links(page: str) -> str:
    """Rewrite root-absolute links/forms/redirect-JS for BASE_PATH. Done once on
    the rendered page so every panel (present and future) can keep writing plain
    '/path' hrefs; a no-op in local dev where BASE_PATH is ''."""
    bp = config.BASE_PATH
    if not bp:
        return page
    return (page.replace('href="/', f'href="{bp}/')
                .replace('action="/', f'action="{bp}/')
                .replace("location.href='/", f"location.href='{bp}/"))


def _shell(active: str, title: str, sub: str, body: str) -> str:
    s = _safety()
    nav = ""
    for group, items in NAV_GROUPS:
        if group:
            nav += f'<div class="nav-group">{group}</div>'
        for href, label, icon in items:
            cls = "active" if href == active else ""
            nav += f'<a class="{cls}" href="{href}">{_icon(icon)}<span>{label}</span></a>'
    if s["live"]:
        send_line = '<span class="dot dot-red"></span>LIVE SEND ENABLED'
    elif s["kill"]:
        send_line = '<span class="dot dot-red"></span>Kill switch ON'
    else:
        send_line = '<span class="dot dot-amber"></span>Dry-run · G-SEND off'
    pill = ('<span class="statpill" style="background:rgba(220,38,38,.1);color:#dc2626">'
            '<span class="dot" style="background:#dc2626"></span>LIVE SEND</span>') if s["live"] else (
            '<span class="statpill"><span class="dot"></span>Dry-run mode · G-SEND off</span>')
    return _prefix_links(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · SettlePay Console</title>
<link rel="preconnect" href="https://api.fontshare.com" crossorigin>
<link rel="preconnect" href="https://cdn.fontshare.com" crossorigin>
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap">
<style>{_STYLE}</style></head><body><div class="app">
<aside class="sidebar">
  <div class="brand"><b>SettlePay</b><span>Operations</span></div>
  <nav class="nav">{nav}</nav>
  <div class="side-status">{send_line}<br>
    <span class="muted" style="color:rgba(255,255,255,.45);font-size:.7rem">
    Resolver: {html.escape(s['resolver'])} · Cap {s['cap']}/inbox/day</span></div>
</aside>
<main class="main">
  <div class="topbar"><div><h1>{html.escape(title)}</h1><div class="sub">{sub}</div></div>{pill}</div>
  <div class="content">{body}</div>
</main></div></body></html>""")


# --------------------------------------------------------------------------- #
#  Combined landing (inbound + outbound at a glance)
# --------------------------------------------------------------------------- #
_ENQ_EMPTY = {"total": 0, "new": 0, "contacted": 0, "quoted": 0, "won": 0,
              "client": 0, "lost": 0, "this_week": 0}
_OUT_EMPTY = {"discovered": 0, "emails_verified": 0, "emails_risky": 0,
              "drafts_awaiting": 0, "sends_dry": 0, "sends_live": 0}


def _tiles(ts) -> str:
    return "".join(
        f'<div class="tile {c}"><div class="n">{n}</div><div class="l">{l}</div><div class="s">{s}</div></div>'
        for c, n, l, s in ts)


@router.get("/", response_class=HTMLResponse)
def root():
    out, enq, ops = dict(_OUT_EMPTY), dict(_ENQ_EMPTY), {}
    try:
        with db.cursor(commit=False) as cur:
            out = stats.overview(cur)
            ops = stats.ops_overview(cur)
    except Exception:
        pass
    try:
        with db.dict_cursor() as cur:
            enq = enquiries.overview(cur) or dict(_ENQ_EMPTY)
    except Exception:
        pass
    et = enq.get("total", 0) or 0
    conv = (100.0 * ((enq.get("won", 0) or 0) + (enq.get("client", 0) or 0)) / et) if et else 0.0
    sent7 = (ops.get("live_7d", 0) or 0)
    reply_rate = (100.0 * ops.get("replies_7d", 0) / sent7) if sent7 else 0.0
    ops_tiles = [
        ("accent", sent7, "Emails sent (7d)", f"{ops.get('dry_7d', 0)} dry-run · {ops.get('live_total', 0)} live all-time"),
        ("", ops.get("replies_7d", 0), "Replies (7d)", f"{reply_rate:.0f}% of live sends"),
        ("", f"£{ops.get('spend_mtd', 0.0):.2f}", "Spend MTD", f"cap £{config.MONTHLY_SPEND_CAP_GBP:.0f}"),
        ("", ops.get("jobs_active", 0), "Jobs running", f"{ops.get('jobs_failed_24h', 0)} failed (24h)"),
    ]
    in_tiles = [
        ("accent", enq.get("total", 0), "Enquiries", "inbound, all time"),
        ("", enq.get("new", 0), "New", "awaiting first contact"),
        ("", enq.get("this_week", 0), "This week", "last 7 days"),
        ("", f"{conv:.0f}%", "Conversion", "won + client"),
    ]
    out_tiles = [
        ("accent", out.get("discovered", 0), "Companies discovered", "outbound, all time"),
        ("", out.get("emails_verified", 0), "Verified", f"+{out.get('emails_risky', 0)} risky"),
        ("", out.get("drafts_awaiting", 0), "Awaiting approval", "in the queue"),
        ("", out.get("sends_dry", 0), "Dry-run sends", f"{out.get('sends_live', 0)} live"),
    ]
    body = f"""
<div class="panel"><h2>Operations</h2>
  <div class="hint">Sent · replies · spend · platform health. <a href="/tasks">Launch a task &rarr;</a></div>
  <div class="kpis">{_tiles(ops_tiles)}</div></div>
<div class="panel"><h2>Inbound — Enquiries</h2>
  <div class="hint">Website enquiries pipeline. <a href="/enquiries">Open enquiries &rarr;</a></div>
  <div class="kpis">{_tiles(in_tiles)}</div></div>
<div class="panel"><h2>Outbound — Outreach</h2>
  <div class="hint">Cold-email pipeline (dry-run; G-SEND off). <a href="/outreach">Open outreach &rarr;</a></div>
  <div class="kpis">{_tiles(out_tiles)}</div></div>"""
    return _shell("/", "Dashboard", "Inbound + outbound at a glance", body)


# --------------------------------------------------------------------------- #
#  Outreach (outbound) dashboard
# --------------------------------------------------------------------------- #
@router.get("/outreach", response_class=HTMLResponse)
def dashboard():
    with db.cursor(commit=False) as cur:
        o = stats.overview(cur)
        verify = stats.verify_breakdown(cur)
        verticals = stats.by_vertical(cur)
        effort = stats.scrape_effort(cur)
        inb = stats.inbound_summary(cur)
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
        f'<tr class="clk" onclick="location.href=\'/outreach/vertical/{html.escape(v["sic"])}\'">'
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
      <dt>Suppressions</dt><dd>{inb['suppressions']} total (opt-outs ∪ bounces ∪ PECR)</dd>
      <dt>Inbound</dt><dd>{inb['reply']} replies · {inb['bounce']} bounces · {inb['unsubscribe']} opt-outs · {inb['complaint']} complaints</dd>
      <dt>Live sends</dt><dd>{o['sends_live']} &nbsp;<span class="badge b-{'error' if _safety()['live'] else 'success'}">{'ENABLED' if _safety()['live'] else 'gated (G-SEND off)'}</span></dd>
      <dt>Per-inbox cap</dt><dd>{_safety()['cap']} / day</dd>
    </dl></div>
</div>
<div class="panel"><h2>Recent activity</h2>
  <div class="hint">Audit trail — one row per lead decision, each carrying its lawful basis.</div>
  <div class="feed">{feed_html}</div>
</div>"""
    return _shell("/outreach", "Outreach", "Live overview of the outreach pipeline", body)


def _badge_event(ev: str) -> str:
    m = {"discovered": "neutral", "classified": "neutral", "enriched": "info",
         "drafted": "info", "approved": "success", "rejected": "error",
         "suppressed": "muted", "discarded": "muted", "dry_run_send": "neutral"}
    return f'<span class="badge b-{m.get(ev,"neutral")}">{html.escape(ev)}</span>'


# --------------------------------------------------------------------------- #
#  Approval queue
# --------------------------------------------------------------------------- #
@router.get("/outreach/queue", response_class=HTMLResponse)
def queue():
    with db.cursor(commit=False) as cur:
        rows = review.list_pending(cur)
        upcoming = send_queue.queue(cur, days=7)
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
        f'<a class="btn btn-primary" href="/outreach/draft/{did}">Review &rarr;</a></div>'
        for did, cn, name, _body in rows
    ) or '<div class="panel"><div class="empty">Nothing awaiting approval. Drafts will appear here once leads are enriched and drafted.</div></div>'
    if upcoming:
        gated = "" if config.send_enabled() else " <b>dry-run</b> (G-SEND not set)"
        sched_rows = "".join(
            f'<tr><td>{d["day"]:%a %d %b}</td><td>{d["count"]}</td>'
            f'<td class="m">{d["first"]:%H:%M}–{d["last"]:%H:%M}</td></tr>'
            for d in upcoming)
        sched = (f'<div class="panel"><h2>Send queue</h2>'
                 f'<div class="hint">Approved drafts are spaced across the send window '
                 f'(UK time) up to the warm-up cap for each day; the overflow rolls to '
                 f'the next weekday. Delivery is{gated or " <b>live</b>"}.</div>'
                 f'<table class="tbl"><thead><tr><th>Day</th><th>Emails</th>'
                 f'<th>Window</th></tr></thead><tbody>{sched_rows}</tbody></table></div>')
    else:
        sched = ""
    head = f'<div class="panel"><h2>{len(rows)} draft{"" if len(rows)==1 else "s"} awaiting your decision</h2>' \
           f'<div class="hint">Approving queues a draft for a specific minute in the send window — sending stays gated behind G-SEND.</div></div>'
    return _shell("/outreach/queue", "Approval queue", "The human gate before any send", head + sched + cards)


@router.get("/outreach/draft/{draft_id}", response_class=HTMLResponse)
def draft_view(request: Request, draft_id: str, err: str = ""):
    with db.cursor(commit=False) as cur:
        cur.execute(
            "select d.company_number, l.company_name, d.body_original, d.status, "
            "e.contact_email, e.email_verify_result, e.website, e.signal, d.subject "
            "from outreach.drafts d join outreach.leads l on l.company_number=d.company_number "
            "left join outreach.enrichment e on e.company_number=d.company_number "
            "where d.id=%s", (draft_id,))
        row = cur.fetchone()
    if not row:
        return HTMLResponse(_shell("/outreach/queue", "Not found", "", '<div class="panel"><div class="empty">Draft not found.</div></div>'), status_code=404)
    cn, name, body, status, email, vres, website, signal, subject = row
    errhtml = f'<div class="alert">{html.escape(err)}</div>' if err else ""
    site = f'<a href="{html.escape(website)}" target="_blank">{html.escape(website)}</a>' if website else "—"
    body_html = f"""
{errhtml}
<div class="two">
  <div class="panel"><h2>Draft message</h2>
    <div class="hint">body_original is immutable. Edit below to approve a revised version (compliance is re-checked on save).</div>
    <form method="post" action="/outreach/approve/{draft_id}">
      {_csrf_field(request)}
      <label class="fld">Subject{'' if subject else ' — MISSING (pre-v2.0 draft; re-draft or write one)'}</label>
      <input name="edited_subject" style="width:100%" maxlength="120"
             value="{html.escape(subject or '')}" placeholder="3-7 words, lowercase, under 50 chars">
      <label class="fld" style="margin-top:.75rem">Body</label>
      <textarea name="edited">{html.escape(body)}</textarea>
      <div class="row">
        <div><label class="fld">Reviewer</label><input name="reviewer" required placeholder="Your name"></div>
        <div style="flex:1"><label class="fld">Note (optional)</label><input name="note" style="width:100%"></div>
      </div>
      <div class="row" style="margin-top:1rem"><button class="btn btn-primary" type="submit">Approve</button></div>
    </form>
    <form method="post" action="/outreach/reject/{draft_id}" style="margin-top:1.25rem;border-top:1px solid var(--line);padding-top:1.1rem">
      {_csrf_field(request)}
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
    <p class="muted" style="margin-top:1rem;font-size:.8rem"><a href="/outreach/lead/{html.escape(cn)}">Full lead record &rarr;</a></p>
  </div>
</div>"""
    return _shell("/outreach/queue", f"Review · {name}", "Approve, edit, or reject this draft", body_html)


@router.post("/outreach/approve/{draft_id}")
def approve(request: Request, draft_id: str, reviewer: str = Form(...),
            edited: str = Form(""), note: str = Form(""), csrf: str = Form(""),
            edited_subject: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    try:
        with db.cursor(commit=False) as cur:
            cur.execute("select body_original, subject from outreach.drafts where id=%s",
                        (draft_id,))
            r = cur.fetchone()
        original = (r[0] if r else "") or ""
        orig_subject = (r[1] if r else "") or ""
        edit_arg = None if edited.strip() == original.strip() else edited
        # unchanged -> None so edit_ratio only counts real reviewer edits
        subj_arg = None if edited_subject.strip() == orig_subject.strip() else edited_subject.strip()
        review.approve(draft_id, reviewer, edited=edit_arg, note=note or None,
                       edited_subject=subj_arg)
    except Exception as e:
        return RedirectResponse(u(f"/outreach/draft/{draft_id}?err={html.escape(str(e))}"), status_code=303)
    return RedirectResponse(u("/outreach/queue"), status_code=303)


@router.post("/outreach/reject/{draft_id}")
def reject(request: Request, draft_id: str, reviewer: str = Form(...),
           note: str = Form(""), csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    try:
        review.reject(draft_id, reviewer, note=note or None)
    except Exception as e:
        return RedirectResponse(u(f"/outreach/draft/{draft_id}?err={html.escape(str(e))}"), status_code=303)
    return RedirectResponse(u("/outreach/queue"), status_code=303)


# --------------------------------------------------------------------------- #
#  Sending — the approved queue, plus the manual override with its undo window
# --------------------------------------------------------------------------- #
_APPROVED_SQL = """
select d.id, d.company_number, l.company_name, coalesce(d.subject_final, d.subject),
       d.scheduled_at, d.outbox_at, e.contact_email, e.contact_tier
from outreach.drafts d
join outreach.leads l on l.company_number = d.company_number
left join outreach.enrichment e on e.company_number = d.company_number
where d.status = 'approved'
  and not exists (select 1 from outreach.sends s where s.draft_id = d.id)
order by d.outbox_at nulls last, d.scheduled_at nulls first, d.created_at
"""


def _outbox_panel(request: Request, rows: list[dict]) -> str:
    """The undo window, rendered. The countdown is client-side and purely cosmetic —
    the server decides when a draft is actually due (outbox.due), so a stopped clock,
    a throttled tab or a closed laptop changes nothing about when it sends."""
    if not rows:
        return ""
    items = ""
    for r in rows:
        left = max(0, int((r["sends_at"] - datetime.now(timezone.utc)).total_seconds()))
        items += f"""<div class="obrow">
  <div><b>{html.escape(r["company_name"])}</b>
    <div class="muted" style="font-size:.78rem">{html.escape(r["subject"] or "(no subject)")}</div></div>
  <div class="obcount" data-left="{left}">{left}s</div>
  <form method="post" action="/outreach/outbox/cancel/{r["id"]}">
    {_csrf_field(request)}<button class="btn btn-ghost" type="submit">Cancel</button></form>
</div>"""
    return f"""<div class="panel" style="border-color:#f59e0b">
<h2>Outbox — {len(rows)} sending shortly</h2>
<div class="hint">Cancel inside the window and the draft goes back to the queue with the
slot it already had. After that it is gone.</div>
{items}
<script>
(function(){{
  var els=[].slice.call(document.querySelectorAll('.obcount'));
  if(!els.length) return;
  setInterval(function(){{
    var live=0;
    els.forEach(function(e){{
      var n=parseInt(e.dataset.left,10)-1; e.dataset.left=n;
      e.textContent = n>0 ? n+'s' : 'sending…'; if(n>-3) live++;
    }});
    if(!live) location.reload();
  }},1000);
  // the countdown is cosmetic; reload once it should have drained to show the truth
  setTimeout(function(){{location.reload();}}, {outbox.UNDO_SECONDS * 1000 + 4000});
}})();
</script></div>"""


@router.get("/outreach/sending", response_class=HTMLResponse)
def sending(request: Request, err: str = ""):
    with db.cursor(commit=False) as cur:
        waiting = outbox.pending(cur)
        cur.execute(_APPROVED_SQL)
        rows = cur.fetchall()
        upcoming = send_queue.queue(cur, days=7)

    in_outbox = {r["id"] for r in waiting}
    trs = ""
    for did, cn, name, subject, slot, obat, email, tier in rows:
        if did in in_outbox:
            continue
        when = f'{slot:%a %d %b · %H:%M}' if slot else '<span class="muted">next tick</span>'
        tier_mark = '<span class="badge b-warning">risky</span>' if tier == "risky" else ""
        trs += f"""<tr>
<td><b>{html.escape(name)}</b><br><span class="muted" style="font-size:.74rem">{html.escape(email or "no contact")}</span> {tier_mark}</td>
<td>{html.escape((subject or "(no subject)")[:60])}</td>
<td class="m">{when}</td>
<td class="num"><form method="post" action="/outreach/outbox/send/{did}" style="display:inline">
{_csrf_field(request)}<button class="btn btn-primary" type="submit">Send now</button></form></td></tr>"""
    if not trs:
        trs = '<tr><td colspan=4 class="empty">Nothing approved and waiting. Approve drafts in the queue and they land here.</td></tr>'

    gated = "" if config.send_enabled() else (
        '<div class="hint"><b>Dry-run.</b> G-SEND is not set, so “Send now” records the '
        'send and exercises every guardrail without a message leaving the mailbox.</div>')
    total_q = sum(d["count"] for d in upcoming)
    errhtml = f'<div class="alert">{html.escape(err)}</div>' if err else ""
    body = f"""{errhtml}
{_outbox_panel(request, waiting)}
<div class="panel"><h2>Approved &amp; queued</h2>
<div class="hint">Each of these already has a slot in the send window. “Send now” jumps the
queue with {outbox.UNDO_SECONDS} seconds to change your mind — it overrides the <em>timing</em>
only: suppression, the corporate check, the warm-up cap and G-SEND all still apply.</div>
{gated}
<table><tr><th>Company</th><th>Subject</th><th>Scheduled</th><th class="num">Override</th></tr>
{trs}</table>
<p class="muted" style="margin-top:1rem;font-size:.78rem">{total_q} queued across the next {len(upcoming)} send day(s).</p>
</div>"""
    return _shell("/outreach/sending", "Sending", "The approved queue and the manual override", body)


@router.post("/outreach/outbox/send/{draft_id}")
def outbox_send(request: Request, draft_id: str, csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    try:
        with db.cursor() as cur:
            outbox.send_now(draft_id, requested_by="console", cur=cur)
    except Exception as e:
        return RedirectResponse(u(f"/outreach/sending?err={html.escape(str(e))}"), status_code=303)
    return RedirectResponse(u("/outreach/sending"), status_code=303)


@router.post("/outreach/outbox/cancel/{draft_id}")
def outbox_cancel(request: Request, draft_id: str, csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    with db.cursor() as cur:
        undone = outbox.cancel(draft_id, requested_by="console", cur=cur)
    if not undone:
        return RedirectResponse(
            u("/outreach/sending?err=Too late — that message had already gone."), status_code=303)
    return RedirectResponse(u("/outreach/sending"), status_code=303)


# --------------------------------------------------------------------------- #
#  Manual research — one URL in, a full company profile out
# --------------------------------------------------------------------------- #
@router.get("/research", response_class=HTMLResponse)
def research_page(request: Request, err: str = ""):
    with db.cursor(commit=False) as cur:
        cur.execute(
            "select p.company_number, l.company_name, p.domain, p.researched_at, "
            "       l.subscriber_class::text, l.state::text "
            "from outreach.profiles p join outreach.leads l on l.company_number = p.company_number "
            "order by p.researched_at desc limit 25")
        recent = cur.fetchall()
    trs = "".join(
        f'<tr class="clk" onclick="location.href=\'/outreach/lead/{html.escape(cn)}\'">'
        f'<td><b>{html.escape(name)}</b></td><td class="m">{html.escape(dom or "—")}</td>'
        f'<td>{_badge(st)}</td>'
        f'<td class="m">{"corporate" if scls == "corporate" else "research-only"}</td>'
        f'<td class="m">{at:%d %b %H:%M}</td></tr>'
        for cn, name, dom, at, scls, st in recent
    ) or '<tr><td colspan=5 class="empty">Nothing researched by hand yet.</td></tr>'
    errhtml = f'<div class="alert">{html.escape(err)}</div>' if err else ""
    body = f"""{errhtml}
<div class="panel"><h2>Research a company</h2>
<div class="hint">Paste a website. It gets the same treatment as a discovered lead:
the site is scraped for a contact, Companies House decides whether it is a corporate
subscriber we may legally cold-email, Places fills in the local record, and the ICP
gate scores the fit — then it is saved as a profile you can draft from.</div>
<form method="post" action="/research">
  {_csrf_field(request)}
  <div class="row" style="align-items:flex-end">
    <div style="flex:1"><label class="fld">Website</label>
      <input name="url" style="width:100%" required placeholder="acme-plumbing.co.uk" autofocus></div>
    <button class="btn btn-primary" type="submit">Research</button>
  </div>
  <label class="fld" style="margin-top:.8rem;font-weight:400">
    <input type="checkbox" name="force" value="1"> Re-research even if we already hold it
  </label>
</form>
<p class="muted" style="margin-top:.9rem;font-size:.78rem">Already on file? You go straight
to the record — nothing is fetched and nothing is spent.</p>
</div>
<div class="panel"><h2>Recently researched</h2>
<table><tr><th>Company</th><th>Domain</th><th>State</th><th>PECR</th><th>Researched</th></tr>
{trs}</table></div>"""
    return _shell("/research", "Research", "Manual company lookup", body)


@router.post("/research")
def research_submit(request: Request, url: str = Form(...), csrf: str = Form(""),
                    force: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    domain = research.normalise_domain(url)
    if not domain:
        return RedirectResponse(
            u(f"/research?err=Not a usable website address: {html.escape(url[:80])}"),
            status_code=303)
    # the dedupe check is DB-only and instant, so it runs HERE rather than in the job:
    # the commonest manual lookup is a company we already hold, and that should be a
    # redirect, not a queued job that spends money to rediscover what is on file
    if not force:
        with db.cursor(commit=False) as cur:
            hit = research.find_existing(domain, cur=cur)
        if hit:
            return RedirectResponse(u(f"/outreach/lead/{hit['company_number']}?known={domain}"),
                                    status_code=303)
    job_id = jobs.enqueue("research_url", {"url": domain, "force": bool(force)},
                          requested_by="console")
    return RedirectResponse(u(f"/jobs/{job_id}"), status_code=303)


# --------------------------------------------------------------------------- #
#  Leads (CRM)
# --------------------------------------------------------------------------- #
@router.get("/outreach/leads", response_class=HTMLResponse)
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
    chips = f'<a class="chip {"active" if not state else ""}" href="/outreach/leads">All <b>{total}</b></a>'
    for st in ["awaiting_approval", "approved", "drafted", "enriched", "discovered", "suppressed", "discarded", "rejected"]:
        if counts.get(st):
            chips += f'<a class="chip {"active" if state==st else ""}" href="/outreach/leads?state={st}">{STATE_STYLE.get(st,(st,))[0]} <b>{counts[st]}</b></a>'

    trs = ""
    for cn, name, sic, st, website, email, verified in rows:
        site = f'<a href="{html.escape(website)}" target="_blank" onclick="event.stopPropagation()">{html.escape(_short(website))}</a>' if website else '<span class="muted">—</span>'
        vmark = '<span class="badge b-success">✓</span>' if verified else ('<span class="muted">—</span>')
        trs += (f'<tr class="clk" onclick="location.href=\'/outreach/lead/{html.escape(cn)}\'">'
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
    return _shell("/outreach/leads", "Leads", "CRM view of every discovered company", body)


def _short(url: str) -> str:
    import re as _re
    return _re.sub(r"^https?://(www\.)?", "", url or "").rstrip("/")[:38]


@router.get("/intelligence", response_class=HTMLResponse)
def intelligence():
    with db.cursor(commit=False) as cur:
        credit = stats.credit_status(cur)
        segments = stats.places_segments(cur)

    # credit burn-down panel
    days = f'{credit["days_left"]} days left' if credit["days_left"] is not None else "set CREDIT_START_DATE for countdown"
    pct = min(100.0, credit["pct"])
    credit_html = f"""<div class="panel">
<div class="row" style="justify-content:space-between;align-items:baseline">
  <h3 style="margin:0">GCP credit</h3><span class="muted">{html.escape(days)}</span></div>
<div style="height:10px;background:var(--line,#e2e8f0);border-radius:6px;overflow:hidden;margin:.6rem 0">
  <div style="height:100%;width:{pct:.1f}%;background:#3B82F6"></div></div>
<div class="row" style="justify-content:space-between">
  <span>£{credit['spent']:.2f} used <span class="muted">({credit['pct']}%)</span></span>
  <span class="muted">£{credit['remaining']:.2f} of £{credit['budget']:.2f} left</span></div>
</div>"""

    # sole-trader intelligence: vertical × class density (corporate = sendable, else salvage)
    by_v: dict[str, dict[str, int]] = {}
    for vertical, cls, n in segments:
        by_v.setdefault(vertical, {})[cls] = n
    trs = ""
    for v in sorted(by_v, key=lambda k: -sum(by_v[k].values())):
        d = by_v[v]
        corp = d.get("corporate", 0)
        research = d.get("individual", 0) + d.get("unknown", 0) + d.get("unclassified", 0)
        tot = corp + research
        rate = f"{100*corp/tot:.0f}%" if tot else "—"
        trs += (f'<tr><td><b>{html.escape(v)}</b></td>'
                f'<td class="num"><span class="badge b-success">{corp}</span></td>'
                f'<td class="num"><span class="muted">{research}</span></td>'
                f'<td class="num">{rate}</td><td class="num">{tot}</td></tr>')
    if not trs:
        trs = '<tr><td colspan=5 class="empty">No Places leads yet — run the discover_places task.</td></tr>'
    seg_html = f"""<div class="panel"><h3 style="margin:0 0 .3rem">Local market — Places segments</h3>
<p class="muted" style="margin:0 0 1rem;font-size:.82rem">Corporate = cold-emailable; research-only = sole traders / unmatched, kept for market intelligence, a re-incorporation watch, and paid-ad / postal personas (never cold-emailed).</p>
<table><tr><th>Vertical</th><th class="num">Corporate</th><th class="num">Research-only</th><th class="num">Corp %</th><th class="num">Total</th></tr>
{trs}</table></div>"""

    return _shell("/intelligence", "Intelligence",
                  "GCP credit burn-down + local-market segments", credit_html + seg_html)


def _tags(items) -> str:
    return ('<div class="tags">' +
            "".join(f'<span class="tag">{html.escape(str(i))}</span>' for i in items) +
            "</div>") if items else '<span class="muted">—</span>'


def _profile_panel(request: Request, profile) -> str:
    """The CRM profile, rendered from the stored facts. Nothing here is stored as
    HTML — `profiles.facts` is jsonb, so the layout can change without a re-scrape and
    the same facts stay queryable and feedable to the drafter."""
    rerun = f"""<form method="post" action="/research" style="display:inline">
{_csrf_field(request)}<input type="hidden" name="url" value="{html.escape((profile or {}).get('domain') or '')}">
<input type="hidden" name="force" value="1">
<button class="btn btn-ghost" type="submit">Re-research</button></form>"""
    if not profile or not profile.get("facts"):
        return f"""<div class="panel"><h2>Research profile</h2>
<div class="empty">No profile yet. Research this company to build one.</div>
<div class="row">{rerun if (profile or {}).get('domain') else ''}</div></div>"""

    f = profile["facts"]
    hooks = "".join(f"<li>{html.escape(str(h))}</li>" for h in (f.get("hooks") or []))
    evidence = "".join(f'<div class="quote">{html.escape(str(e))}</div>'
                       for e in (f.get("evidence") or []))
    src = ", ".join(str(s.get("kind")) for s in (profile.get("sources") or [])) or "—"
    people = f.get("roles_mentioned") or []
    people_row = (f"<dt>Decision-makers</dt><dd>{_tags(people)}</dd>") if people else ""
    return f"""<div class="panel"><h2>Research profile</h2>
<div class="hint">{html.escape(f.get("one_liner") or "")}</div>
<dl class="kv">
  <dt>Services</dt><dd>{_tags(f.get("services"))}</dd>
  <dt>Takes payment by</dt><dd>{_tags(f.get("payment_methods"))}</dd>
  <dt>Booking</dt><dd>{html.escape(f.get("booking_method") or "—")}</dd>
  <dt>Customers</dt><dd>{html.escape(f.get("customers") or "—")}</dd>
  <dt>Coverage</dt><dd>{html.escape(f.get("coverage") or "—")}</dd>
  {people_row}
</dl>
{f'<h3 style="margin:1rem 0 .2rem;font-size:.9rem">Angles for the email</h3><ul class="hooks">{hooks}</ul>' if hooks else ''}
{f'<h3 style="margin:1rem 0 .2rem;font-size:.9rem">Evidence</h3>{evidence}' if evidence else ''}
<div class="row" style="margin-top:1rem;justify-content:space-between;align-items:center">
  <span class="muted" style="font-size:.76rem">Sources: {html.escape(src)} ·
    researched {profile["researched_at"]:%d %b %Y}</span>{rerun}</div>
</div>"""


@router.get("/outreach/lead/{company_number}", response_class=HTMLResponse)
def lead_detail(request: Request, company_number: str, known: str = ""):
    with db.cursor(commit=False) as cur:
        cur.execute(
            "select company_name, company_number, company_type, company_status, "
            "sic_codes, subscriber_class::text, state::text, registered_address "
            "from outreach.leads where company_number=%s", (company_number,))
        lead = cur.fetchone()
        if not lead:
            return HTMLResponse(_shell("/outreach/leads", "Not found", "", '<div class="panel"><div class="empty">Lead not found.</div></div>'), status_code=404)
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
        profile = research.get_profile(company_number, cur=cur)

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

    banner = (f'<div class="panel" style="border-color:#3B82F6"><b>Already on file.</b> '
              f'{html.escape(known)} was researched before, so nothing was fetched or spent — '
              f'this is the record we hold. Use <em>Re-research</em> below to refresh it.</div>'
              ) if known else ""

    body = f"""{banner}
<div class="two">
  <div class="panel"><h2>{html.escape(name)}</h2><div class="hint">{html.escape(cn)}</div>{facts}</div>
  <div class="panel"><h2>Enrichment</h2><div class="hint">Discovery → scrape → verify</div>{enr_html}</div>
</div>
{_profile_panel(request, profile)}
<div class="panel"><h2>Drafts</h2>{draft_html}</div>
<div class="panel"><h2>Audit timeline</h2><div class="feed">{feed}</div></div>
<p class="muted" style="font-size:.8rem"><a href="/outreach/leads">&larr; Back to leads</a></p>"""
    return _shell("/outreach/leads", name, "Lead record", body)


# --------------------------------------------------------------------------- #
#  Settings (read-only runtime posture)
# --------------------------------------------------------------------------- #
@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    s = _safety()
    try:
        db_ok = db.ping()
    except Exception:
        db_ok = False
    try:
        seq = load_sequence_config()
    except Exception:
        seq = {}
    try:
        db_kill = monitor.db_kill_switch()
    except Exception:
        db_kill = False
    env_kill = bool(s["kill"])
    win = seq.get("send_window", {})
    warm = seq.get("warmup", {})
    kill_state = ('<span class="badge b-error">ON</span>' if (env_kill or db_kill)
                  else '<span class="badge b-success">off</span>')
    kill_form = f"""<form method="post" action="/settings/kill-switch" class="row" style="margin-top:.8rem">
      {_csrf_field(request)}
      <input type="hidden" name="action" value="{'off' if db_kill else 'on'}">
      <div style="flex:1"><label class="fld">Reason</label><input name="reason" style="width:100%" placeholder="why"></div>
      <button class="btn btn-ghost" type="submit">{'Clear DB kill switch' if db_kill else 'Trip kill switch'}</button>
    </form>""" + ('<div class="hint" style="margin-top:.5rem">Env KILL_SWITCH is set — clearing the DB flag will NOT resume sending.</div>' if env_kill else "")
    ops_panel = f"""<div class="panel"><h2>Operational controls</h2>
    <div class="hint">The kill switch blocks every outreach send (dry-run included); operator alerts and digests still deliver.</div>
    <dl class="kv">
      <dt>Kill switch</dt><dd>{kill_state} <span class="muted">env: {'set' if env_kill else 'unset'} · db flag: {'set' if db_kill else 'unset'}</span></dd>
      <dt>Console auth</dt><dd>{'<span class="badge b-success">enforced</span>' if webauth.auth_configured() else '<span class="badge b-warning">OPEN — local dev (set CONSOLE_PASSWORD_HASH + SESSION_SECRET)</span>'}</dd>
      <dt>Autonomy</dt><dd>{'<span class="badge b-info">full chain</span>' if config.PIPELINE_AUTONOMOUS else '<span class="badge b-muted">classify+send only (PIPELINE_AUTONOMOUS unset)</span>'}</dd>
      <dt>Auto-approve</dt><dd>{'<span class="badge b-error">ENABLED</span>' if config.AUTO_APPROVE_ENABLED else '<span class="badge b-success">off — human approval required</span>'}</dd>
    </dl>{kill_form}</div>"""
    cfg = ops_panel + f"""<div class="two">
  <div class="panel"><h2>Send safety</h2>
    <div class="hint">The gates that keep this from emailing anyone before you're ready.</div>
    <dl class="kv">
      <dt>Live send (G-SEND)</dt><dd>{'<span class="badge b-error">ENABLED</span>' if s['live'] else '<span class="badge b-success">gated — off</span>'}</dd>
      <dt>Kill switch</dt><dd>{'<span class="badge b-error">ON (all sends blocked)</span>' if s['kill'] else '<span class="badge b-muted">off</span>'}</dd>
      <dt>Per-inbox cap</dt><dd>{s['cap']} / day</dd>
      <dt>Risky (catch-all) send</dt><dd>{'<span class="badge b-error">ENABLED</span>' if s['risky_send'] else '<span class="badge b-success">off — needs RISKY_SEND_ENABLED</span>'}</dd>
      <dt>Sending domain</dt><dd>{html.escape(s['sender'])}</dd>
      <dt>Send window</dt><dd>{win.get('start_hour','?')}:00–{win.get('end_hour','?')}:00 UK <span class="muted">(Tue–Thu)</span></dd>
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
<div class="two">
  <div class="panel"><h2>Deliverability (pre-live-send)</h2>
    <div class="hint">Required before G-SEND. See docs/pre-send-blockers.md.</div>
    <dl class="kv">
      <dt>Warm-up ramp</dt><dd>day-1 {warm.get('daily_caps',['?'])[0]} → steady {warm.get('steady','?')} / inbox / day</dd>
      <dt>Sending domain</dt><dd>{html.escape((s['sender'].split('@')[-1] if '@' in s['sender'] else s['sender']))}</dd>
      <dt>SPF / DKIM / DMARC</dt><dd class="muted">verify: <code>python -m outreach.dns_auth</code></dd>
    </dl></div>
  <div class="panel"><h2>Inbound ingestion</h2>
    <div class="hint">Reply / bounce / unsubscribe feedback loop into suppressions.</div>
    <dl class="kv">
      <dt>Source</dt><dd>{html.escape(config.INBOUND_SOURCE)} {'<span class="badge b-muted">Gmail read — pending</span>' if config.INBOUND_SOURCE!='inline' else ''}</dd>
      <dt>Run</dt><dd class="muted"><code>python -m outreach.inbound</code></dd>
      <dt>Effect</dt><dd>bounce→suppress+bounced · opt-out→suppress · reply→replied</dd>
    </dl></div>
</div>
<div class="two">
  <div class="panel"><h2>Inbound enquiries (CRM)</h2>
    <div class="hint">Where the Enquiries section reads from.</div>
    <dl class="kv">
      <dt>Database</dt><dd>{'<span class="badge b-success">connected</span>' if db_ok else '<span class="badge b-error">not reachable</span>'}</dd>
      <dt>Enquiries table</dt><dd>public.{html.escape(config.ENQUIRY_SOURCE_TABLE)}</dd>
      <dt>Capture</dt><dd><span class="badge b-success">live</span> <span class="muted">(website form → Supabase)</span></dd>
      <dt>Consultations</dt><dd>public.bookings <span class="muted">(Cal.com webhook → Schedule)</span></dd>
    </dl></div>
  <div class="panel"><h2>Console</h2>
    <div class="hint">This unified operations surface.</div>
    <dl class="kv">
      <dt>Sections</dt><dd>Inbound (Enquiries · Schedule) + Outbound (Outreach)</dd>
      <dt>Access</dt><dd>localhost only · no auth</dd>
    </dl></div>
</div>
<div class="note">This is a read-only view. Changing any of these means editing <b>outreach/.env</b> (or
<b>sequence_config.json</b>) and restarting the service — deliberately not editable from the browser, since
this console has no authentication.</div>"""
    return _shell("/settings", "Settings", "Runtime configuration & safety posture (read-only)", cfg)


# --------------------------------------------------------------------------- #
#  Enquiries (inbound) — website form CRM
# --------------------------------------------------------------------------- #
@router.get("/enquiries", response_class=HTMLResponse)
def enquiries_list(status: str = ""):
    try:
        with db.dict_cursor() as cur:
            counts = enquiries.status_counts(cur)
            rows = enquiries.list_enquiries(cur, status)
    except Exception:
        counts, rows = {}, []
    total = sum(counts.values())
    chips = f'<a class="chip {"active" if not status else ""}" href="/enquiries">All <b>{total}</b></a>'
    for st in PIPELINE_ORDER:
        if counts.get(st):
            chips += (f'<a class="chip {"active" if status==st else ""}" href="/enquiries?status={st}">'
                      f'{ENQUIRY_STYLE[st][0]} <b>{counts[st]}</b></a>')
    trs = ""
    for r in rows:
        trs += (f'<tr class="clk" onclick="location.href=\'/enquiry/{html.escape(str(r["id"]))}\'">'
                f'<td><b>{html.escape(r["business"])}</b></td>'
                f'<td>{html.escape(r["name"])}</td>'
                f'<td><a href="mailto:{html.escape(r["email"])}" onclick="event.stopPropagation()">{html.escape(r["email"])}</a></td>'
                f'<td>{_enq_badge(r["status"])}</td>'
                f'<td class="num muted">{_ago(r["created_at"])}</td></tr>')
    trs = trs or '<tr><td colspan=5 class="empty">No enquiries match this filter.</td></tr>'
    body = f"""<div class="chips">{chips}</div>
<div class="panel"><table>
<tr><th>Business</th><th>Name</th><th>Email</th><th>Status</th><th class="num">Received</th></tr>
{trs}</table>
<p class="muted" style="margin-top:1rem;font-size:.78rem">Showing {len(rows)} enquir{"y" if len(rows)==1 else "ies"}.</p>
</div>"""
    return _shell("/enquiries", "Enquiries", "Every inbound enquiry — your CRM", body)


@router.get("/enquiry/{lead_id}", response_class=HTMLResponse)
def enquiry_detail(request: Request, lead_id: str, saved: int = 0):
    try:
        with db.dict_cursor() as cur:
            lead = enquiries.get(cur, lead_id)
    except Exception:
        lead = None
    if not lead:
        return HTMLResponse(_shell("/enquiries", "Not found", "",
                            '<div class="panel"><div class="empty">Enquiry not found.</div></div>'), status_code=404)
    options = "".join(
        f'<option value="{st}"{" selected" if lead["status"] == st else ""}>{ENQUIRY_STYLE[st][0]}</option>'
        for st in PIPELINE_ORDER)
    saved_html = '<div class="ok">Saved.</div>' if saved else ""
    received = lead["created_at"].strftime("%d %b %Y, %H:%M") if lead.get("created_at") else "—"
    body = f"""
{saved_html}
<div class="two">
  <div class="panel"><h2>{html.escape(lead["business"])}</h2>
    <div class="hint">Enquiry received {_ago(lead["created_at"])}</div>
    <dl class="kv">
      <dt>Contact</dt><dd>{html.escape(lead["name"])}</dd>
      <dt>Email</dt><dd><a href="mailto:{html.escape(lead["email"])}">{html.escape(lead["email"])}</a></dd>
      <dt>Status</dt><dd>{_enq_badge(lead["status"])}</dd>
      <dt>Source</dt><dd>{html.escape(lead.get("source") or "—")}</dd>
      <dt>Received</dt><dd>{received}</dd>
    </dl>
    <h2 style="margin-top:1.5rem">Their message</h2>
    <div class="body-box" style="margin-top:.6rem">{html.escape(lead["message"])}</div>
  </div>
  <div class="panel"><h2>Manage</h2>
    <div class="hint">Move the enquiry through your pipeline and keep private notes.</div>
    <form method="post" action="/enquiry/{html.escape(str(lead["id"]))}">
      {_csrf_field(request)}
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
    return _shell("/enquiries", lead["business"], "Enquiry record", body)


@router.post("/enquiry/{lead_id}")
def enquiry_update(request: Request, lead_id: str, status: str = Form(...),
                   notes: str = Form(""), csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    try:
        with db.dict_cursor(commit=True) as cur:
            enquiries.update(cur, lead_id, status, notes)
    except Exception:
        return RedirectResponse(u(f"/enquiry/{lead_id}"), status_code=303)
    return RedirectResponse(u(f"/enquiry/{lead_id}?saved=1"), status_code=303)


# --------------------------------------------------------------------------- #
#  Schedule (inbound) — consultations booked via Cal.com
# --------------------------------------------------------------------------- #
@router.get("/schedule", response_class=HTMLResponse)
def schedule():
    connected, upcoming, recent = False, [], []
    try:
        with db.dict_cursor() as cur:
            if enquiries.bookings_exists(cur):
                connected = True
                upcoming = enquiries.upcoming_bookings(cur)
                recent = enquiries.recent_bookings(cur)
    except Exception:
        connected, upcoming, recent = False, [], []

    if not connected:
        body = """
<div class="note">Consultations appear here once the <b>public.bookings</b> table exists
(<code>supabase&nbsp;db&nbsp;push</code>) and the Cal.com webhook is connected.</div>
<div class="panel"><div class="empty">No bookings connected yet.</div></div>"""
        return _shell("/schedule", "Schedule", "Consultations & bookings", body)

    now = datetime.now(timezone.utc)
    week = sum(1 for b in upcoming
               if b["start_at"] and (b["start_at"] - now).total_seconds() < 7 * 86400)
    nxt = _when(upcoming[0]["start_at"]) if upcoming else "—"
    tiles = [
        ("accent", len(upcoming), "Upcoming", "confirmed consultations"),
        ("", week, "This week", "next 7 days"),
    ]
    kpis = "".join(
        f'<div class="tile {cls}"><div class="n">{n}</div><div class="l">{l}</div><div class="s">{s}</div></div>'
        for cls, n, l, s in tiles)

    def _who(b: dict) -> str:
        name = html.escape(b.get("attendee_name") or "—")
        email = b.get("attendee_email") or ""
        sub = (f'<br><span class="muted" style="font-size:.74rem">{html.escape(email)}</span>'
               if email else "")
        if b.get("lead_id"):
            sub += (f' <a href="/enquiry/{html.escape(str(b["lead_id"]))}" '
                    f'class="muted" style="font-size:.72rem">· from enquiry</a>')
        return f'<b>{name}</b>{sub}'

    def _join(b: dict) -> str:
        u = b.get("join_url")
        if not u:
            return '<span class="muted">—</span>'
        return (f'<a class="btn btn-ghost" style="padding:.32rem .85rem;font-size:.76rem" '
                f'href="{html.escape(u)}" target="_blank" rel="noopener">Join</a>')

    up = "".join(
        f'<tr><td>{_when(b["start_at"])}</td><td>{_who(b)}</td>'
        f'<td>{_join(b)}</td><td>{_booking_badge(b["status"])}</td></tr>'
        for b in upcoming) or '<tr><td colspan=4 class="empty">No upcoming consultations.</td></tr>'

    body = f"""<div class="kpis">{kpis}</div>
<div class="panel"><h2>Upcoming consultations</h2>
  <div class="hint">Booked via Cal.com · next up: {html.escape(nxt)}</div>
  <table><tr><th>When (UK)</th><th>Who</th><th>Link</th><th>Status</th></tr>{up}</table>
</div>"""

    if recent:
        rec = "".join(
            f'<tr><td>{_when(b["start_at"])}</td><td>{_who(b)}</td>'
            f'<td>{_booking_badge(b["status"])}</td></tr>'
            for b in recent)
        body += f"""<div class="panel"><h2>Recent &amp; past</h2>
  <div class="hint">Completed and cancelled consultations.</div>
  <table><tr><th>When (UK)</th><th>Who</th><th>Status</th></tr>{rec}</table></div>"""

    return _shell("/schedule", "Schedule", "Consultations booked via Cal.com", body)


# --------------------------------------------------------------------------- #
#  Login (bespoke session auth; OPEN in local dev when auth is unconfigured)
# --------------------------------------------------------------------------- #
def _login_page(err: str = "") -> str:
    alert = f'<div class="alert">{html.escape(err)}</div>' if err else ""
    return _prefix_links(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in · SettlePay Console</title>
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,600,700&display=swap">
<style>{_STYLE}</style></head><body>
<div style="min-height:100vh;display:flex;align-items:center;justify-content:center">
  <div class="panel" style="width:340px">
    <h2>SettlePay Operations</h2>
    <div class="hint">Sign in to the console.</div>
    {alert}
    <form method="post" action="/login">
      <label class="fld">Password</label>
      <input type="password" name="password" required autofocus style="width:100%">
      <div class="row" style="margin-top:1.1rem">
        <button class="btn btn-primary" type="submit">Sign in</button>
      </div>
    </form>
  </div>
</div></body></html>""")


@router.get("/login", response_class=HTMLResponse)
def login_page():
    if not webauth.auth_configured():
        return RedirectResponse(u("/"), status_code=303)
    return HTMLResponse(_login_page())


@router.post("/login")
def login_submit(request: Request, password: str = Form(...)):
    if not webauth.auth_configured():
        return RedirectResponse(u("/"), status_code=303)
    ip = _client_ip(request)
    if not _login_limiter.allow(ip):
        return HTMLResponse(_login_page("Too many attempts — try again in a few minutes."),
                            status_code=429)
    if not webauth.verify_password(password):
        _login_limiter.record_failure(ip)
        return HTMLResponse(_login_page("Wrong password."), status_code=401)
    _login_limiter.reset(ip)
    resp = RedirectResponse(u("/"), status_code=303)
    resp.set_cookie(webauth.COOKIE_NAME, webauth.create_session(),
                    max_age=config.SESSION_TTL_HOURS * 3600, httponly=True,
                    samesite="lax", secure=(request.url.scheme == "https"),
                    path=config.BASE_PATH or "/")
    return resp


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    resp = RedirectResponse(u("/login"), status_code=303)
    resp.delete_cookie(webauth.COOKIE_NAME, path=config.BASE_PATH or "/")
    return resp


# --------------------------------------------------------------------------- #
#  Operate — task launcher + jobs (the canvas)
# --------------------------------------------------------------------------- #
JOB_STYLE = {"queued": "neutral", "running": "info", "succeeded": "success",
             "failed": "error", "cancelled": "muted"}


def _job_badge(status: str) -> str:
    return f'<span class="badge b-{JOB_STYLE.get(status, "neutral")}">{html.escape(status)}</span>'


def _param_input(p) -> str:
    if p.kind == "bool":
        checked = " checked" if p.default else ""
        return (f'<label class="fld" style="display:flex;align-items:center;gap:.5rem;margin:.6rem 0">'
                f'<input type="checkbox" name="{p.name}" value="1"{checked} style="min-width:0"> {html.escape(p.label)}</label>')
    itype = "number" if p.kind == "int" else "text"
    dflt = "" if p.default is None else html.escape(str(p.default))
    req = " required" if p.required else ""
    return (f'<label class="fld">{html.escape(p.label)}</label>'
            f'<input type="{itype}" name="{p.name}" value="{dflt}"{req} style="min-width:140px;width:100%">')


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request):
    groups: dict[str, list] = {}
    for spec in jobs.REGISTRY.values():
        groups.setdefault(spec.group, []).append(spec)
    body = ""
    for group in sorted(groups):
        cards = ""
        for spec in sorted(groups[group], key=lambda s: s.title):
            fields = "".join(_param_input(p) for p in spec.params)
            confirm = ('<label class="fld" style="display:flex;align-items:center;gap:.5rem">'
                       '<input type="checkbox" required style="min-width:0"> I understand this acts on real data</label>'
                       if spec.destructive else "")
            cards += f"""<div class="panel" style="margin-bottom:1rem">
  <h2>{html.escape(spec.title)}</h2><div class="hint">{html.escape(spec.description)}</div>
  <form method="post" action="/tasks/launch">
    {_csrf_field(request)}<input type="hidden" name="kind" value="{spec.kind}">
    {fields}{confirm}
    <div class="row" style="margin-top:.9rem"><button class="btn btn-ghost" type="submit">Launch</button></div>
  </form></div>"""
        body += (f'<div class="hint" style="margin:.4rem 0 .8rem;text-transform:uppercase;'
                 f'letter-spacing:.08em;font-weight:700">{html.escape(group)}</div>'
                 f'<div class="two">{cards}</div>')
    return _shell("/tasks", "Launch", "Run any pipeline task on demand — it queues as a job", body)


@router.post("/tasks/launch")
async def tasks_launch(request: Request):
    form = await request.form()
    if not _csrf_ok(request, str(form.get("csrf", ""))):
        return _CSRF_DENIED
    kind = str(form.get("kind", ""))
    if kind not in jobs.REGISTRY:
        return HTMLResponse("<h3>Unknown task.</h3>", status_code=404)
    params = {k: str(v) for k, v in form.items() if k not in ("kind", "csrf")}
    job_id = jobs.enqueue(kind, params, requested_by="operator")
    return RedirectResponse(u(f"/jobs/{job_id}"), status_code=303)


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page():
    with db.dict_cursor(commit=False) as cur:
        cur.execute("select id, kind, status, requested_by, created_at, started_at, finished_at "
                    "from outreach.jobs order by id desc limit 100")
        rows = cur.fetchall()
    trs = ""
    for r in rows:
        dur = ""
        if r["started_at"] and r["finished_at"]:
            dur = f'{(r["finished_at"] - r["started_at"]).total_seconds():.1f}s'
        trs += (f'<tr class="clk" onclick="location.href=\'/jobs/{r["id"]}\'">'
                f'<td class="num">{r["id"]}</td><td><b>{html.escape(r["kind"])}</b></td>'
                f'<td>{_job_badge(r["status"])}</td><td>{html.escape(r["requested_by"])}</td>'
                f'<td class="num muted">{_ago(r["created_at"])}</td><td class="num muted">{dur}</td></tr>')
    trs = trs or '<tr><td colspan=6 class="empty">No jobs yet — launch one from the Launch page.</td></tr>'
    body = f"""<div class="panel"><table>
<tr><th class="num">#</th><th>Task</th><th>Status</th><th>By</th><th class="num">Created</th><th class="num">Took</th></tr>
{trs}</table></div>"""
    return _shell("/jobs", "Jobs", "Everything the platform has run or is running", body)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int):
    with db.dict_cursor(commit=False) as cur:
        cur.execute("select * from outreach.jobs where id=%s", (job_id,))
        j = cur.fetchone()
    if not j:
        return HTMLResponse(_shell("/jobs", "Not found", "", '<div class="panel"><div class="empty">Job not found.</div></div>'), status_code=404)
    active = j["status"] in ("queued", "running")
    prog = j.get("progress") or {}
    done, total = prog.get("done"), prog.get("total")
    bar = ""
    if done is not None and total:
        pct = 100.0 * done / max(total, 1)
        bar = (f'<div class="ftrack" style="margin:.6rem 0"><div class="ffill" style="width:{pct:.0f}%"></div></div>'
               f'<div class="muted" style="font-size:.8rem">{done} / {total}</div>')
    log_html = "".join(
        f'<div class="ev"><span class="t">{html.escape(str(e.get("t",""))[11:19])}</span>'
        f'<span>{html.escape(str(e.get("msg","")))}</span></div>'
        for e in (prog.get("log") or [])[-60:]) or '<div class="empty">No log lines.</div>'
    result_html = (f'<div class="body-box">{html.escape(json.dumps(j["result"], indent=2, default=str)[:6000])}</div>'
                   if j.get("result") is not None else '<div class="empty">No result yet.</div>')
    err_html = (f'<div class="alert" style="white-space:pre-wrap;font-family:var(--mono);font-size:.78rem">'
                f'{html.escape((j.get("error") or "")[-1500:])}</div>' if j.get("error") else "")
    cancel = (f'<form method="post" action="/jobs/{job_id}/cancel" style="display:inline">'
              f'{_csrf_field(request)}<button class="btn btn-ghost" type="submit">Cancel</button></form>'
              if active else "")
    refresh = '<meta http-equiv="refresh" content="3">' if active else ""
    body = f"""{refresh}
<div class="two">
  <div class="panel"><h2>Job #{j["id"]} — {html.escape(j["kind"])}</h2>
    <dl class="kv">
      <dt>Status</dt><dd>{_job_badge(j["status"])} {cancel}</dd>
      <dt>Requested by</dt><dd>{html.escape(j["requested_by"])}</dd>
      <dt>Created</dt><dd>{_ago(j["created_at"])}</dd>
      <dt>Params</dt><dd class="muted" style="font-family:var(--mono);font-size:.78rem">{html.escape(json.dumps(j.get("params") or {}))}</dd>
    </dl>{bar}{err_html}</div>
  <div class="panel"><h2>Result</h2>{result_html}</div>
</div>
<div class="panel"><h2>Log</h2><div class="feed">{log_html}</div></div>
<p class="muted" style="font-size:.8rem"><a href="/jobs">&larr; All jobs</a></p>"""
    return _shell("/jobs", f"Job #{j['id']}", j["kind"], body)


@router.post("/jobs/{job_id}/cancel")
def job_cancel(request: Request, job_id: int, csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    jobs.cancel(job_id)
    return RedirectResponse(u(f"/jobs/{job_id}"), status_code=303)


# --------------------------------------------------------------------------- #
#  Vertical drilldown — per-SIC funnel + graduation progress
# --------------------------------------------------------------------------- #
@router.get("/outreach/vertical/{sic}", response_class=HTMLResponse)
def vertical_detail(sic: str):
    with db.cursor(commit=False) as cur:
        cur.execute("select state::text, count(*) from outreach.leads "
                    "where sic_codes[1]=%s group by 1 order by 2 desc", (sic,))
        states = cur.fetchall()
        metrics = next((m for m in graduation.vertical_metrics(cur) if m.get("vertical") == sic), None)
    label = stats.sic_label(sic)
    chips = "".join(
        f'<a class="chip" href="/outreach/leads?vertical={html.escape(sic)}&state={st}">'
        f'{STATE_STYLE.get(st, (st,))[0]} <b>{n}</b></a>' for st, n in states) or \
        '<div class="empty">No leads in this vertical yet.</div>'
    g = graduation_thresholds()
    if metrics:
        grad = f"""<table><tr><th>Metric</th><th class="num">Now</th><th class="num">Needed</th></tr>
<tr><td>Reviewed drafts</td><td class="num">{metrics.get('reviewed', 0)}</td><td class="num muted">&ge; {g.get('min_reviewed_drafts_per_vertical')}</td></tr>
<tr><td>Approved unedited</td><td class="num">{(metrics.get('approved_unedited_rate') or 0):.0%}</td><td class="num muted">&ge; {g.get('min_approved_unedited_rate', 0):.0%}</td></tr>
<tr><td>Bounce rate</td><td class="num">{(metrics.get('bounce_rate') or 0):.1%}</td><td class="num muted">&lt; {g.get('max_bounce_rate', 0):.0%}</td></tr>
<tr><td>Complaint rate</td><td class="num">{(metrics.get('complaint_rate') or 0):.2%}</td><td class="num muted">&lt; {g.get('max_complaint_rate', 0):.1%}</td></tr></table>"""
    else:
        grad = '<div class="empty">No reviewed drafts for the current playbook version yet.</div>'
    body = f"""<div class="panel"><h2>Leads by state</h2>
  <div class="hint">Click a state to open the filtered CRM view.</div>
  <div class="chips">{chips}</div></div>
<div class="panel"><h2>Graduation to auto-send</h2>
  <div class="hint">Progress for the CURRENT playbook version — a new version resets the window by design.</div>
  {grad}</div>
<p class="muted" style="font-size:.8rem"><a href="/outreach">&larr; Outreach overview</a></p>"""
    return _shell("/outreach", f"{label}", f"Vertical drilldown · SIC {sic}", body)


# --------------------------------------------------------------------------- #
#  Kill switch (operational control on Settings)
# --------------------------------------------------------------------------- #
@router.post("/settings/kill-switch")
def kill_switch_update(request: Request, action: str = Form(...),
                       reason: str = Form(""), csrf: str = Form("")):
    if not _csrf_ok(request, csrf):
        return _CSRF_DENIED
    monitor.set_kill_switch(action == "on", reason=reason or "set from console",
                            updated_by="operator")
    return RedirectResponse(u("/settings"), status_code=303)


app.include_router(router, prefix=config.BASE_PATH)
