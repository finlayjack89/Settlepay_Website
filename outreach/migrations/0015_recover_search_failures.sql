-- 0015 — re-open the leads that were discarded for OUR failures rather than for a verdict,
-- and give refresh_facts the marker it needs to stop re-doing the same 25 rows.
--
-- Shipped WITH the 0014 code change, never before it: 0010's header explains why — repair
-- the data first and the next tick simply re-destroys it. The write path now parks these,
-- so this is a one-off catch-up for rows written before that landed.
--
-- Measured on the live database at the time of writing:
--
--   267  discarded with email_verify_result in ('no_email','recipient_mismatch')
--          113  a website resolved but the scrape found zero addresses
--          107  candidates WERE found and every one rejected — mostly the business's own
--               address on a sibling TLD, or a name-matching freemail
--           47  no website resolved at all
--     4  discarded by the draft envelope — three of them a subject line 51 characters
--        long, one a body a single word over the limit
--
-- Each already cost Places credit, a Firecrawl resolve, up to three Firecrawl scrapes and
-- a Gemini call. None is a statement about the business.
--
-- Idempotent: only rows still `discarded` for these reasons move, and park_count is SET
-- rather than incremented, so a re-run cannot burn the retry budget.

-- refresh_facts had no way to remember it had already looked at a lead. Its predicate
-- ("location is null") stays true for anything genuinely unplaceable, and its write
-- touches only `enrichment`, so `order by leads.updated_at` never moved — it re-did
-- identical work on the SAME 25 rows every run and rows 26+ were unreachable.
alter table outreach.enrichment add column if not exists facts_refreshed_at timestamptz;

comment on column outreach.enrichment.facts_refreshed_at is
  'When the drafting constants were last recomputed. Orders the refresh queue so an unplaceable lead cannot starve the rest.';

-- 1. enrichment search failures -> parked, immediately eligible for the enrich backlog
update outreach.leads l
   set state         = 'parked',
       parked_reason = 'enrich: ' || e.email_verify_result,
       parked_at     = now() - make_interval(hours => 48),
       park_count    = 1,
       updated_at    = now()
  from outreach.enrichment e
 where e.company_number = l.company_number
   and l.state = 'discarded'
   and e.email_verify_result in ('no_email', 'recipient_mismatch');

-- 2. draft envelope failures -> parked with a 'draft ' reason, so draft.run retries them
--    directly instead of paying to re-enrich a lead whose contact is already good
update outreach.leads l
   set state         = 'parked',
       parked_reason = 'draft envelope: recovered by 0015',
       parked_at     = now() - make_interval(hours => 48),
       park_count    = 1,
       updated_at    = now()
 where l.state = 'discarded'
   and exists (select 1 from outreach.audit_log a
                where a.company_number = l.company_number
                  and a.event = 'draft_discarded'
                  and a.reason like 'envelope unfixable%')
   and exists (select 1 from outreach.enrichment e
                where e.company_number = l.company_number
                  and e.contact_email is not null);
