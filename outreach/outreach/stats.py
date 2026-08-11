"""Read-only analytics for the operator dashboard.

Aggregates the outreach funnel from outreach.leads / enrichment / drafts / sends /
audit_log. Pure reads — never writes. Every number here is derived from the live
Supabase `outreach` schema, so the dashboard reflects real pipeline performance.
"""
from __future__ import annotations

from .targeting import SIC_LABELS  # single source of truth for SIC -> label


def sic_label(sic: str | None) -> str:
    """First SIC code -> human label for the per-vertical breakdown. Unknown codes
    fall through to the raw code so nothing is silently hidden."""
    if not sic:
        return "Unknown"
    return SIC_LABELS.get(sic, sic)


def _scalar(cur, q, params=()):
    cur.execute(q, params)
    row = cur.fetchone()
    return (row[0] if row and row[0] is not None else 0)


def credit_status(cur) -> dict:
    """GCP-credit burn-down vs the $300/90-day budget (separate from the cash cap)."""
    from . import config, spend
    spent = spend.credit_spent_gbp(cur)
    budget = config.CREDIT_BUDGET_GBP
    out = {"spent": round(spent, 2), "budget": round(budget, 2),
           "remaining": round(max(0.0, budget - spent), 2),
           "pct": round(100 * spent / budget, 1) if budget else 0.0, "days_left": None}
    if config.CREDIT_START_DATE:
        cur.execute("select 90 - (current_date - %s::date)", (config.CREDIT_START_DATE,))
        out["days_left"] = max(0, cur.fetchone()[0])
    return out


def places_segments(cur) -> list[tuple]:
    """Places reservoir grouped by vertical × subscriber class — the sole-trader
    intelligence view (corporate = sendable, individual/unknown = research-only salvage)."""
    cur.execute(
        "select coalesce(registered_address->>'primary_type','(unknown)') vertical, "
        "coalesce(subscriber_class::text,'unclassified') cls, count(*) n "
        "from outreach.leads where source='places' "
        "group by 1,2 order by vertical, cls")
    return cur.fetchall()


def review_backlog(cur) -> int:
    """Drafts waiting on a human. Drafting is the last credit-spending stage before
    the manual gate, so this is what must throttle it: without a cap the pipeline
    drafts for ever and pays to write email nobody has read yet."""
    return _scalar(cur, "select count(*) from outreach.drafts "
                        "where status = 'awaiting_approval'")


def runway(cur, *, window_days: int = 14) -> dict:
    """How many days of sending each stage is holding, at the rate we actually send.

    The funnel counts alone cannot answer the only question that matters day to day —
    "will this keep running, and if not, which stage runs dry first?" A 14,000-lead
    backlog looks like abundance right up until you notice only 136 of them are enriched
    and the drafter is what's starving.

    Rate: measured live sends per day over the window, falling back to today's PLANNED
    capacity when nothing has sent. That fallback is deliberate. Dividing by a measured
    rate of zero yields infinite runway, which is precisely the reading this pipeline
    would have given while it sat idle for a fortnight — every stage "fine", nothing
    moving. `rate_basis` says which number was used, so the answer is never silently
    hypothetical.
    """
    from . import config, schedule, sequence

    sent = _scalar(cur, "select count(*) from outreach.sends where mode='live' "
                        "and created_at >= now() - make_interval(days => %s)",
                   (window_days,))
    measured = sent / window_days if sent else 0.0
    if measured > 0:
        rate, basis = measured, "measured"
    else:
        seq = sequence.load_sequence_config()
        try:
            rate = float(schedule.daily_capacity(
                sequence.local_now(seq).date(), cur=cur,
                inbox=config.GMAIL_SENDER or "unset", seq=seq))
        except Exception:
            rate = 0.0
        basis = "planned"

    # pipeline order matters below — the bottleneck rule reads it
    stages = [
        # each is stock WAITING for the named stage to act on it
        ("crossref", "select count(*) from outreach.leads "
                     "where source='places' and subscriber_class is null "
                     "and state='discovered'"),
        ("enrich", "select count(*) from outreach.leads "
                   "where subscriber_class='corporate' and state='discovered'"),
        ("draft", "select count(*) from outreach.leads where state='enriched'"),
        ("review", "select count(*) from outreach.drafts where status='awaiting_approval'"),
        ("send", "select count(*) from outreach.drafts "
                 "where status='approved' and not exists ("
                 "  select 1 from outreach.sends s "
                 "  where s.draft_id = outreach.drafts.id and s.mode='live')"),
    ]
    out = {"rate_per_day": round(rate, 2), "rate_basis": basis,
           "window_days": window_days, "sent_in_window": sent, "stages": {}}
    order = [name for name, _ in stages]
    for name, sql in stages:
        stock = _scalar(cur, sql)
        out["stages"][name] = {"stock": stock,
                               "days": round(stock / rate, 1) if rate > 0 else None}

    # An empty stage is either CAUGHT UP or STARVING, and the difference is everything.
    # crossref sitting at zero with 7,416 leads queued behind it means it has finished its
    # work, not that the pipeline is dry — so calling it the bottleneck sends you to fix
    # the one stage that is keeping up. A stage counts as starving only if nothing
    # downstream of it is holding stock either.
    def starving(i: int) -> bool:
        name = order[i]
        if out["stages"][name]["stock"] > 0:
            return False
        return all(out["stages"][n]["stock"] == 0 for n in order[i + 1:])

    live = {n: out["stages"][n]["days"] for i, n in enumerate(order)
            if out["stages"][n]["days"] is not None
            and (out["stages"][n]["stock"] > 0 or starving(i))}
    out["bottleneck"] = min(live, key=live.get) if live else None
    out["days_of_runway"] = live.get(out["bottleneck"]) if out["bottleneck"] else None
    return out


def reservoir_status(cur, target: int) -> dict:
    """The demand-pull reservoir: `ready` = enriched-and-fit leads awaiting a draft;
    `backlog` = corporate leads discovered but not yet enriched. `deficit` drives how
    much discover/enrich run this tick (0 => pool full => the expensive stages idle)."""
    ready = _scalar(cur, "select count(*) from outreach.leads where state='enriched'")
    backlog = _scalar(
        cur, "select count(*) from outreach.leads where subscriber_class='corporate' and state='discovered'")
    deficit = max(0, target - ready)
    return {"ready": ready, "backlog": backlog, "target": target, "deficit": deficit}


def overview(cur) -> dict:
    """The headline funnel: discovery -> compliance -> enrichment -> drafting -> send."""
    d: dict = {}
    d["discovered"] = _scalar(cur, "select count(*) from outreach.leads")
    d["corporate"] = _scalar(
        cur, "select count(*) from outreach.leads where subscriber_class='corporate'")
    d["suppressed"] = _scalar(
        cur, "select count(*) from outreach.leads where state='suppressed'")
    d["websites"] = _scalar(
        cur, "select count(*) from outreach.enrichment where website is not null")
    d["emails_found"] = _scalar(
        cur, "select count(*) from outreach.enrichment where contact_email is not null")
    d["emails_verified"] = _scalar(
        cur, "select count(*) from outreach.enrichment where email_verified")
    d["emails_risky"] = _scalar(
        cur, "select count(*) from outreach.enrichment where contact_tier='risky'")
    d["discarded"] = _scalar(
        cur, "select count(*) from outreach.leads where state='discarded'")
    # Parked is NOT discarded, and conflating the two is what hid this for so long: these
    # are leads OUR machinery failed on (verifier dry, scrape empty, wrong site resolved)
    # and will retry — not leads we ruled out. A rising count here means the pipeline is
    # its own bottleneck, which is worth being able to see.
    d["parked"] = _scalar(
        cur, "select count(*) from outreach.leads where state='parked'")

    cur.execute(
        "select count(*), "
        "count(*) filter (where status='awaiting_approval'), "
        "count(*) filter (where status in ('approved','sent')), "
        "count(*) filter (where status='rejected'), "
        "count(*) filter (where status in ('approved','sent') and body_final=body_original) "
        "from outreach.drafts")
    total, awaiting, approved, rejected, unedited = cur.fetchone()
    d["drafts_total"] = total or 0
    d["drafts_awaiting"] = awaiting or 0
    d["approved"] = approved or 0
    d["drafts_rejected"] = rejected or 0
    d["approved_unedited"] = unedited or 0
    d["unedited_rate"] = (unedited / approved) if approved else 0.0

    cur.execute(
        "select count(*) filter (where mode='dry_run'), "
        "count(*) filter (where mode='live') from outreach.sends")
    dry, live = cur.fetchone()
    d["sends_dry"] = dry or 0
    d["sends_live"] = live or 0
    return d


def verify_breakdown(cur) -> list[tuple]:
    """MillionVerifier result distribution — where contactability is won or lost."""
    cur.execute(
        "select coalesce(email_verify_result,'(not reached)'), count(*) "
        "from outreach.enrichment group by 1 order by 2 desc")
    return cur.fetchall()


def scrape_effort(cur) -> dict:
    """Contact-source split (info@ guess vs httpx scrape vs Firecrawl fallback) +
    total emails harvested. Tracked in enrichment.scraped from this build onward."""
    cur.execute(
        "select count(*) filter (where scraped->>'source'='guess'), "
        "count(*) filter (where scraped->>'source'='httpx'), "
        "count(*) filter (where scraped->>'source'='firecrawl'), "
        "coalesce(sum((scraped->>'emails_found')::int),0), "
        "count(*) filter (where scraped is not null) "
        "from outreach.enrichment")
    guess_n, httpx_n, fc_n, emails, tracked = cur.fetchone()
    return {"guess": guess_n or 0, "httpx": httpx_n or 0, "firecrawl": fc_n or 0,
            "emails_found_total": emails or 0, "tracked": tracked or 0}


def decision_maker_status(cur) -> dict:
    """How well we reach the person who decides — and the numbers that decide whether to
    BUY anything to improve it.

    The research doc gives thresholds, but they only mean something against our own data,
    and both of ours currently point AWAY from spending:

      * named_rate  < 35%  -> stop hunting personal addresses; the FAO tier is the play
      * catch_all   > 60%  -> a catch-all-resolving verifier (ZeroBounce/Bouncer) would pay
                              for itself. Measured around 20%, so it would not.

    `addressed_rate` is the one that actually matters: the share of contactable leads where
    we can name a human in the email, whether or not we hold their personal address.
    """
    cur.execute(
        "select count(*) filter (where contact_email is not null), "
        "       count(*) filter (where contact_tier = 'named'), "
        "       count(*) filter (where contact_tier = 'role_fao'), "
        "       count(*) filter (where contact_tier = 'verified'), "
        "       count(*) filter (where contact_tier = 'risky'), "
        "       count(*) filter (where contact_method = 'sourced'), "
        "       count(*) filter (where contact_method = 'derived') "
        "from outreach.enrichment")
    have, named, fao, role, risky, sourced, derived = cur.fetchone()
    have, named, fao = have or 0, named or 0, fao or 0
    role, risky = role or 0, risky or 0
    tiered = named + fao + role + risky
    addressed = named + fao
    cur.execute("select count(*), count(distinct company_number) from outreach.officers")
    officer_rows, officer_companies = cur.fetchone()
    cur.execute("select count(*) filter (where outcome='miss'), count(*) "
                "from outreach.lookup_attempts")
    cached_miss, cached_total = cur.fetchone()

    def pct(n, d):
        return round(100.0 * n / d, 1) if d else 0.0

    return {
        "with_contact": have,
        "named": named,                        # a personal mailbox we hold
        "fao": fao,                            # shared mailbox, named addressee
        "role_only": role,                     # shared mailbox, nobody named
        "risky": risky,
        "sourced": sourced or 0,               # they published it
        "derived": derived or 0,               # inferred from a CONFIRMED pattern
        "officers_stored": officer_rows or 0,
        "companies_with_officers": officer_companies or 0,
        "lookups_cached": cached_total or 0,
        "lookups_saved": cached_miss or 0,     # paid calls the cache has prevented
        # --- the rates the doc's thresholds are about ---
        "named_rate": pct(named, have),
        "addressed_rate": pct(addressed, have),
        "catch_all_rate": pct(risky, tiered),
        "buy_catch_all_resolver": pct(risky, tiered) > 60,
        # only meaningful once there is a sample worth judging on
        "stop_hunting_personal": have >= 100 and pct(named, have) < 35,
    }


def by_vertical(cur) -> list[dict]:
    """Funnel split by lead source vertical (first SIC code) — shows which
    targeting actually yields contactable companies."""
    cur.execute(
        "select coalesce(l.sic_codes[1],'?') as sic, "
        "count(*) as total, "
        "count(*) filter (where l.subscriber_class='corporate') as corporate, "
        "count(e.website) as websites, "
        "count(e.contact_email) as emails, "
        "count(*) filter (where e.email_verified) as verified "
        "from outreach.leads l "
        "left join outreach.enrichment e on e.company_number = l.company_number "
        "group by 1 order by 2 desc")
    out = []
    for sic, total, corp, sites, emails, verified in cur.fetchall():
        out.append({
            "sic": sic, "label": sic_label(sic), "total": total,
            "corporate": corp, "websites": sites, "emails": emails,
            "verified": verified,
            "yield": (verified / total) if total else 0.0,
        })
    return out


def inbound_summary(cur) -> dict:
    """Inbound handling + suppression totals — the PECR/reputation feedback loop."""
    cur.execute("select kind, count(*) from outreach.replies group by 1")
    by = dict(cur.fetchall())
    return {"reply": by.get("reply", 0), "bounce": by.get("bounce", 0),
            "unsubscribe": by.get("unsubscribe", 0), "complaint": by.get("complaint", 0),
            "suppressions": _scalar(cur, "select count(*) from outreach.suppressions")}


def recent_activity(cur, limit: int = 18) -> list[tuple]:
    """The audit trail tail — every lead decision with its lawful basis on file."""
    cur.execute(
        "select a.created_at, a.event, a.company_number, l.company_name, a.reason "
        "from outreach.audit_log a "
        "left join outreach.leads l on l.company_number = a.company_number "
        "order by a.created_at desc limit %s", (limit,))
    return cur.fetchall()


def ops_overview(cur) -> dict:
    """The transparency numbers the operator asked the dashboard for: emails sent,
    replies, spend vs cap, and whether the platform's own jobs are healthy."""
    cur.execute(
        "select count(*) filter (where mode='live' and created_at > now() - interval '7 days'), "
        "count(*) filter (where mode='dry_run' and created_at > now() - interval '7 days'), "
        "count(*) filter (where mode='live') from outreach.sends")
    live_7d, dry_7d, live_total = cur.fetchone()
    cur.execute(
        "select count(*) filter (where kind='reply'), count(*) filter (where kind='bounce') "
        "from outreach.replies where created_at > now() - interval '7 days'")
    replies_7d, bounces_7d = cur.fetchone()
    cur.execute("select count(*) filter (where status in ('queued','running')), "
                "count(*) filter (where status='failed' and created_at > now() - interval '24 hours') "
                "from outreach.jobs")
    jobs_active, jobs_failed_24h = cur.fetchone()
    from . import spend as spend_mod
    return {"live_7d": live_7d, "dry_7d": dry_7d, "live_total": live_total,
            "replies_7d": replies_7d, "bounces_7d": bounces_7d,
            "jobs_active": jobs_active, "jobs_failed_24h": jobs_failed_24h,
            "spend_mtd": spend_mod.month_total_gbp(cur=cur)}
