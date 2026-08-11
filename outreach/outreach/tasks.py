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

from . import config, crossref, db, decisionmakers, dns_auth, draft, firewall, followup
from . import feedback, graduation, inbound
from . import critic as critic_mod
from . import enrich as enrich_mod
from . import find_leads, places, report, research, rework as rework_mod
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


@task("auction_run", "Auction platform recon",
      "Paste an auction platform link: scrape its auctioneer directory, then run each "
      "house through the full chain — own website, how they take payment, Companies "
      "House PECR gate + directors, verified decision-maker email — score it, and land "
      "the results in the lead pipeline. Paid (Firecrawl/Gemini/verifier); ~8s per house.",
      params=(Param("url", "Platform link or key", default="easyliveauction.com"),
              Param("limit", "How many auction houses", kind="int", default=25),
              Param("ingest", "Add results to the lead pipeline", kind="bool", default=True)))
def auction_run_task(ctx, url="easyliveauction.com", limit=25, ingest=True):
    from .auctions import run as auction_run
    from .auctions.sources import platform_for_url
    platform = platform_for_url(url)          # raises PlatformNotSupported with a message
    ctx.log(f"platform: {platform} (from {url!r})")
    return auction_run.run_pipeline(platform, limit=limit, ingest=ingest, log=ctx.log)


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


@task("decision_makers", "Find decision-makers",
      "Fetch directors from Companies House and try to CONFIRM one named work email per "
      "lead via MillionVerifier (never a guess). Off unless DECISION_MAKER_ENABLED is set; "
      "moves outreach to named individuals (full UK GDPR).",
      params=(Param("limit", "How many", kind="int", default=10),))
def decision_makers_task(ctx, limit=10):
    return decisionmakers.run(limit=limit)


@task("refresh_facts", "Refresh drafting constants",
      "Re-resolve each lead's verified constants (company, contact, location, region, "
      "established) from their own website, a trading listing, and Companies House. "
      "Touches nothing else — never re-verifies a contact, never discards a lead.",
      params=(Param("limit", "How many", kind="int", default=25),))
def refresh_facts_task(ctx, limit=25):
    out = enrich_mod.refresh_facts(limit=limit)
    ctx.log(f"{out['refreshed']} refreshed · {out['placed']} now placeable")
    return out


@task("draft", "Draft emails",
      "Draft playbook emails for enriched leads into the approval queue.",
      params=(Param("limit", "How many", kind="int", default=10),))
def draft_task(ctx, limit=10):
    return {"drafted": draft.run(limit=limit)}


@task("rework", "Re-work stale leads",
      "Return queue drafts whose FACTS predate the current enrichment to the enriched "
      "pool, so the decision-maker waterfall and the facts refresh run on them before "
      "they are re-drafted. Every rejection a human has written on this pipeline was a "
      "facts error, so re-drafting alone reproduces it in fresher prose. Keeps the paid "
      "contact; retires an approved draft as a recorded decision, never a silent rewrite. "
      "DRY RUN by default — it reports what it would touch and writes nothing.",
      params=(Param("limit", "How many", kind="int", default=25),
              Param("dry_run", "Dry run", kind="bool", default=True)),
      destructive=True)
def rework_task(ctx, limit=25, dry_run=True):
    out = rework_mod.run(limit=limit, dry_run=dry_run)
    for lead in out["leads"][:20]:
        ctx.log(f"  {lead['company_name']} — {lead['why']}")
    ctx.log(f"{out['stale']} stale · {out['reworked']} reworked"
            + (" (DRY RUN — nothing written)" if dry_run else ""))
    return out


@task("redraft", "Re-draft stale queue",
      "Re-write approval-queue drafts written by an older playbook, using the current "
      "constants and gates. Only awaiting-approval drafts; the old copy is superseded, "
      "never deleted, and a replacement that fails its gates leaves the original in place.",
      params=(Param("limit", "How many", kind="int", default=25),))
def redraft_task(ctx, limit=25):
    out = draft.redraft_stale(limit=limit)
    ctx.log(f"{out['redrafted']} redrafted · {out['failed_kept_old']} kept older copy")
    return out


@task("critic", "Critique drafts (shadow)",
      "An independent model (OpenAI, decorrelated from the Gemini drafter) scores each "
      "queued draft against its own facts block: grounding, recipient fit, ICP fit and "
      "compliance are hard failures; prose is only a soft one — because every rejection "
      "a human has written on this pipeline was a facts error, not a prose error. In "
      "shadow mode it records a verdict and changes NOTHING, so its agreement with your "
      "decisions can be measured before it is trusted with any of them.",
      params=(Param("limit", "How many", kind="int", default=10),))
def critic_task(ctx, limit=10):
    out = critic_mod.run(limit=limit)
    ctx.log(f"{out.get('judged', 0)} judged · {out.get('passed', 0)} pass · "
            f"{out.get('failed', 0)} fail · mode={out.get('mode')}")
    return out


@task("critic_calibrate", "Calibrate the critic on your past decisions",
      "Runs the critic over drafts YOU have already approved or rejected — the answer key. "
      "Shadow mode otherwise measures agreement only against decisions made from now on, "
      "which means weeks before there is anything to judge it by. All four of your real "
      "rejections are in this set, so it also tests the critic against the failures that "
      "actually happened. Writes only the critic_* columns; your decisions are untouched.",
      params=(Param("limit", "How many", kind="int", default=25),))
def critic_calibrate_task(ctx, limit=25):
    out = critic_mod.run(limit=limit, calibrate=True)
    ctx.log(f"{out.get('judged', 0)} judged · {out.get('passed', 0)} pass · "
            f"{out.get('failed', 0)} fail")
    with db.cursor(commit=False) as cur:
        agree = critic_mod.agreement(cur)
    ctx.log(f"agreement {agree['agreement_rate']:.0%} of {agree['compared']} · "
            f"{agree['false_pass']} false pass · {agree['false_fail']} false fail")
    return {**out, "agreement": agree}


@task("critic_agreement", "Critic vs human agreement",
      "How often the critic's verdict matched a REAL human decision (system/auto rows "
      "excluded). Reports false-pass and false-fail separately: a false pass is a bad "
      "email sent, a false fail is a good email held — only the first is a reason not "
      "to hand over.")
def critic_agreement_task(ctx):
    with db.cursor(commit=False) as cur:
        out = critic_mod.agreement(cur)
    ctx.log(f"{out['compared']} compared · {out['agreement_rate']:.0%} agreement · "
            f"{out['false_pass']} false pass · {out['false_fail']} false fail")
    return out


@task("review_feedback", "What your rejections are about",
      "Classifies every reviewer note and routes it to the stage that caused it, then "
      "reports which stage your rejections are really about. Backfills notes written "
      "before the classifier existed; idempotent.")
def review_feedback_task(ctx):
    filled = feedback.backfill()
    with db.cursor(commit=False) as cur:
        out = feedback.summary(cur)
    ctx.log(f"{filled['classified']} newly classified")
    if out["worst_stage"]:
        ctx.log(f"{out['worst_share']:.0%} of your rejections are about: {out['worst_stage']}")
    return {**out, "backfilled": filled}


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
