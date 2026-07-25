-- outreach-build · migration 0012 — the drafting FACTS block
--
-- Drafts were asserting things nobody had verified: a greeting naming a person who was
-- never on file ("Hi John," on a lead with contact_name null), and a location taken from
-- the registered office (routinely the accountant's town, not where the business trades).
-- The root cause is that `enrichment.signal` is FREE TEXT — a paragraph the drafter reads
-- and re-asserts, with no way to tell a fact from a plausible-sounding guess.
--
-- enrichment.facts replaces that guesswork with resolved CONSTANTS, each carrying its own
-- provenance and verified flag:
--
--   {"company_name":   {"value": "Adam Partridge Auctioneers", "source": "own_site",  "verified": true},
--    "contact_name":   {"value": "Robert",       "source": "ch_officer_verified_email","verified": true},
--    "location":       {"value": "Macclesfield", "source": "places_listing",          "verified": true},
--    "vertical":       {"value": "auctioneers",  "source": "sic_label",               "verified": true},
--    "payment_method": {"value": "bank transfer","source": "site_quote",              "verified": true}}
--
-- A field that could not be established is present with value null — an EXPLICIT unknown,
-- not an absent key. That distinction is the whole point: the drafter is told "there is no
-- location for this lead" rather than being left a gap it will fill with something
-- plausible. Only `company_name` is mandatory; the rest are optional-but-declared.
--
-- The signal column stays: it remains useful colour for the human reviewer and for the
-- ICP-fit record. It simply stops being the source of named entities.

alter table outreach.enrichment add column if not exists facts jsonb;

-- Rows only become draftable once facts are resolved, so the drafter's backlog query
-- filters on this. Partial: unresolved rows are the ones we never want to scan past.
create index if not exists enrichment_facts_idx
  on outreach.enrichment ((facts is not null)) where facts is not null;

-- Backfill what we can already stand behind, so existing enriched leads stay draftable.
-- Deliberately conservative: company_name comes from the register and contact_name only
-- where a contact was actually verified. location is left NULL rather than inheriting the
-- registered-office town that caused the wrong-location drafts in the first place —
-- re-enrichment is what fills it, from a trading source.
-- NB: no jsonb_strip_nulls — a null `value` is the explicit "we do not know this", and
-- stripping it back to an absent key would lose exactly the distinction being introduced.
update outreach.enrichment e
set facts = jsonb_build_object(
      'company_name', jsonb_build_object(
          'value', l.company_name, 'source', 'companies_house', 'verified', true),
      'contact_name', jsonb_build_object(
          'value', e.contact_name, 'source',
          case when e.contact_name is null then null else 'enrichment_backfill' end,
          'verified', e.contact_name is not null),
      'location',       jsonb_build_object('value', null, 'source', null, 'verified', false),
      'vertical',       jsonb_build_object('value', null, 'source', null, 'verified', false),
      'payment_method', jsonb_build_object('value', null, 'source', null, 'verified', false)
    )
from outreach.leads l
where l.company_number = e.company_number
  and e.facts is null;
