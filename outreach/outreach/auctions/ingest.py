"""Drafting hand-off (Phase 6) — push enriched auction leads into the outreach DB so the
EXISTING draft stage picks them up. Optional (off by default): the sample run just writes
files; production ingest is an explicit choice.

A corporate auction lead becomes a normal `outreach.leads` row (source = the platform
key, e.g. 'easylive' / 'saleroom' / 'bidspotter' — so yield is attributable per platform)
plus an `outreach.enrichment` row carrying the resolved website, the
best verified contact, the payment-hook signal, and the decision-maker name. From there
the pipeline's draft → review → send chain runs unchanged — including the "Dear <name>,"
greeting and every compliance gate. Non-corporate leads are inserted as research-only
(state stays 'discovered', never drafted).
"""
from __future__ import annotations

import json

from .. import audit, db, facts
from .models import EnrichedLead


def _facts(lead: EnrichedLead) -> dict:
    """The auction path resolves the richest constants in the pipeline: the location is
    the auctioneer's own listed address, and payment_method is a sentence quoted verbatim
    from their own site rather than inferred from a category."""
    payment = None
    if lead.payment_methods:
        payment = ", ".join(lead.payment_methods)
    return facts.build(
        company_name=lead.business_name, company_name_source=f"{lead.platform}_listing",
        contact_name=lead.decision_maker_name,
        contact_name_source="ch_officer_verified_email" if lead.decision_maker_name else None,
        location=lead.location,
        location_source="platform_listing" if lead.location else None,
        vertical=lead.categories[0] if lead.categories else None,
        vertical_source="platform_listing" if lead.categories else None,
        payment_method=payment,
        payment_method_source="site_quote" if payment else None)


def _signal(lead: EnrichedLead) -> str:
    bits = [lead.signal] if lead.signal else []
    if lead.payment_quote:
        bits.append(f'They tell winners: "{lead.payment_quote}"')
    elif lead.payment_methods:
        bits.append("Pays by " + ", ".join(lead.payment_methods))
    return " ".join(bits)[:500] or f"{lead.business_name} — auctioneer via {lead.platform}"


def to_pipeline(leads: list[EnrichedLead], *, cur) -> dict:
    inserted = skipped = 0
    for lead in leads:
        cn = lead.company_number or f"URL:{lead.domain}" if lead.domain else None
        if not cn:
            skipped += 1
            continue
        corporate = lead.pecr_class == "corporate"
        state = "enriched" if (corporate and (lead.decision_maker_email or lead.generic_email)) \
            else "discovered"
        addr = {"postcode": lead.postcode, "website": lead.own_website,
                "categories": lead.categories, "platform": lead.platform,
                "listing_url": lead.listing_url}
        cur.execute(
            "insert into outreach.leads (company_number, company_name, registered_address, "
            " subscriber_class, state, source, domain, matched_company_number, crossref_checked_at) "
            "values (%s,%s,%s::jsonb,%s,%s,%s,%s,%s,now()) "
            "on conflict (company_number) do update set "
            "company_name=excluded.company_name, domain=coalesce(leads.domain, excluded.domain), "
            "updated_at=now()",
            (cn, lead.business_name, json.dumps(addr), lead.pecr_class, state,
             lead.platform, lead.domain, lead.company_number))
        email = lead.decision_maker_email or lead.generic_email
        tier = "named" if lead.decision_maker_email else ("verified" if lead.generic_email else None)
        if email:
            cur.execute(
                "insert into outreach.enrichment (company_number, website, domain, "
                " contact_email, contact_name, contact_tier, email_verified, "
                " email_verify_result, signal, scraped, facts) "
                "values (%s,%s,%s,%s,%s,%s,true,'ok',%s,%s::jsonb,%s::jsonb) "
                "on conflict (company_number) do update set "
                "contact_email=excluded.contact_email, contact_name=excluded.contact_name, "
                "contact_tier=excluded.contact_tier, signal=excluded.signal, "
                "facts=excluded.facts",
                (cn, lead.own_website, lead.domain, email,
                 lead.decision_maker_name, tier, _signal(lead),
                 json.dumps({"source": lead.platform, "payment_methods": lead.payment_methods,
                             "score": lead.score}),
                 facts.dumps(_facts(lead))))
        audit.record(cn, "researched", source="auctions",
                     lawful_basis=audit.LEGITIMATE_INTERESTS,
                     reason=f"{lead.platform} lead, score {lead.score}, {lead.pecr_class}",
                     cur=cur)
        inserted += 1
    return {"inserted": inserted, "skipped": skipped}
