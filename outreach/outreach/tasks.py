"""Task registry — the canvas's launchable units.

Each task is a thin wrapper over an existing pipeline entrypoint; the jobs
framework (jobs.py) supplies queueing, params, progress and history, and the
console renders launch forms straight from each task's Param specs. Adding a
future capability (clay_push, prompt_review, ...) is ONE @task function here —
no framework change.

Live sending still passes every send_one guardrail: a task can request
mode='live' but nothing leaves an inbox unless a human has set G_SEND.
"""
from __future__ import annotations

from . import config, crossref, dns_auth, draft, firewall, followup, graduation, inbound
from . import enrich as enrich_mod
from . import find_leads, places, report, research
from . import run as run_mod
from . import send as send_mod
from .jobs import Param, task


@task("tick", "Pipeline tick",
      "Advance every lead one step — the scheduler runs exactly this.",
      params=(Param("dry_run", "Dry run", kind="bool", default=True),))
def tick(ctx, dry_run=True):
    summary = run_mod.run(stage="all", dry_run=dry_run)
    ctx.log(f"stages: {', '.join(sorted(summary.get('steps', {})))}" if "steps" in summary
            else str(summary))
    return summary


@task("discover", "Discover leads",
      "Companies House sweep of the ICP verticals into outreach.leads.",
      params=(Param("target", "How many", kind="int", default=10),))
def discover(ctx, target=10):
    return find_leads.run(target=target, sic_codes=config.TARGET_SIC_CODES or None)


@task("discover_places", "Discover (Places, local)",
      "Google Places sweep of the town×vertical grid into leads (paid: GCP credit). "
      "Paged by a cursor so each run advances the grid.",
      params=(Param("count", "How many queries", kind="int", default=16),))
def discover_places(ctx, count=16):
    return places.discover_grid(count=count)


@task("crossref", "Cross-reference (PECR gate)",
      "Match Places leads to Companies House; only confident active-corporate matches "
      "become sendable, the rest are kept research-only.",
      params=(Param("limit", "How many", kind="int", default=50),))
def crossref_task(ctx, limit=50):
    return crossref.run(limit=limit)


@task("research_url", "Research a website",
      "Paste a company's URL: scrape the site, cross-reference Companies House, pull "
      "the local Places record, score ICP fit, and build a CRM profile. Skips instantly "
      "(and spends nothing) if the domain is already on file.",
      params=(Param("url", "Website URL", required=True),
              Param("force", "Re-research even if already held", kind="bool", default=False)))
def research_url_task(ctx, url="", force=False):
    return research.run(url, force=force, log=ctx.log)


@task("classify", "Classify (PECR firewall)",
      "Classify unclassified leads; individual/unknown are hard-suppressed.")
def classify(ctx):
    return firewall.run()


@task("enrich", "Enrich leads",
      "Resolve websites, find + verify contacts, write signals (paid: MV/Firecrawl).",
      params=(Param("limit", "How many", kind="int", default=10),))
def enrich(ctx, limit=10):
    return {"enriched": enrich_mod.discover_and_run(limit=limit)}


@task("draft", "Draft emails",
      "Draft playbook emails for enriched leads into the approval queue.",
      params=(Param("limit", "How many", kind="int", default=10),))
def draft_task(ctx, limit=10):
    return {"drafted": draft.run(limit=limit)}


@task("followup", "Generate follow-ups",
      "Touch-2 drafts for live-sent leads past the cadence delay (needs approval).",
      params=(Param("limit", "How many", kind="int", default=10),))
def followup_task(ctx, limit=10):
    return {"followups": followup.run(limit=limit)}


@task("send_batch", "Send batch",
      "Send every approved draft. Dry-run unless G-SEND is humanly cleared.",
      params=(Param("mode", "Mode (dry_run|live)", default="dry_run"),),
      destructive=True)
def send_batch(ctx, mode="dry_run"):
    if mode not in ("dry_run", "live"):
        raise ValueError("mode must be dry_run or live")
    return {"sends": send_mod.run(mode=mode)}


@task("inbound_poll", "Poll inbound",
      "Read the mailbox: bounces/opt-outs suppress, replies advance leads.")
def inbound_poll(ctx):
    return inbound.run()


@task("auto_approve", "Graduation auto-approve",
      "Auto-approve drafts in graduated verticals (double-gated, spot-checked).")
def auto_approve(ctx):
    return {"actions": graduation.run()}


@task("dns_check", "DNS auth check",
      "Verify SPF/DKIM/DMARC on the sending domain (deliverability gate).")
def dns_check(ctx):
    domain = dns_auth.domain_of(config.GMAIL_SENDER)
    if not domain:
        return {"skipped": "GMAIL_SENDER not configured"}
    return dns_auth.check_domain(domain)


@task("digest_daily", "Daily digest",
      "Email the operator digest (sent/replies/bounces/spend); date-throttled.",
      group="admin")
def digest_daily(ctx):
    return report.send_daily_digest()


@task("migrate", "Apply migrations",
      "Apply migrations/*.sql to the database (idempotent).", group="admin",
      destructive=True)
def migrate_task(ctx):
    from . import migrate
    return {"applied": migrate.apply()}
