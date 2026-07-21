-- outreach-build · migration 0010 — recover leads discarded by a verifier OUTAGE
--
-- On 2026-07-20 the MillionVerifier balance went negative. Every check from that point
-- returned {"result": "error", "error": "Insufficient credits"}, contact_tier came back
-- NULL, and enrich._persist read that as "unverifiable contact" and discarded the lead.
-- 178 companies were thrown away in a day, each of which HAD a contact address; the
-- pipeline would have kept doing it every tick, silently, until someone noticed the
-- reservoir draining.
--
-- The code fix (enrich.TRANSIENT_RESULTS) makes a verifier that fails to ANSWER defer a
-- lead instead of discarding it, and stops the batch after VERIFIER_DOWN_AFTER
-- consecutive failures so a dead verifier can't burn scrapes. This migration repairs the
-- rows the old behaviour already destroyed. It ships WITH that fix, deliberately: repair
-- before the fix and the next tick simply re-discards everything.
--
-- Idempotent, and narrow by construction: it only touches leads that are 'discarded'
-- AND whose enrichment recorded a transient verifier failure AND which actually had a
-- contact email. A lead discarded for a real reason — invalid address, no address,
-- wrong ICP — matches none of those and is left exactly as it is.

-- 1. put the leads back in the queue
update outreach.leads l
   set state = 'discovered', updated_at = now()
  from outreach.enrichment e
 where e.company_number = l.company_number
   and l.state = 'discarded'
   and e.email_verify_result in ('error', 'verify_error')
   and e.contact_email is not null;

-- 2. drop the enrichment rows that recorded the non-verdict. The enrich backlog selects
--    leads with NO enrichment row, so leaving these behind would restore the lead to
--    'discovered' and then hide it from the retry for ever — worse than the bug.
delete from outreach.enrichment
 where email_verify_result in ('error', 'verify_error')
   and contact_email is not null;

-- 3. leave a trace: this was a data repair, not something the pipeline decided
insert into outreach.audit_log (company_number, event, source, lawful_basis, reason)
select l.company_number, 'verify_deferred', 'migration_0010', 'legitimate interests',
       'restored: discarded by a MillionVerifier outage, not by a verdict on the address'
  from outreach.leads l
 where l.state = 'discovered'
   and exists (select 1 from outreach.audit_log a
                where a.company_number = l.company_number
                  and a.event = 'discarded'
                  and a.reason like 'unverifiable contact (%error)')
   and not exists (select 1 from outreach.audit_log a
                    where a.company_number = l.company_number
                      and a.source = 'migration_0010');
