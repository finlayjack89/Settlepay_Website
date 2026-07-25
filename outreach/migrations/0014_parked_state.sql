-- 0014 — the PARKED lead state.
--
-- `discarded` was doing four different jobs at once:
--
--   1. a verdict about the address      (verify said 'invalid')          -> terminal, correct
--   2. a verdict about the business     (not ICP fit)                    -> terminal, correct
--   3. ABSENCE OF EVIDENCE              ('no_email' — our search failed) -> not a verdict
--   4. FAILURE OF OUR OWN MACHINERY     (a subject line 51 chars long,
--                                        the verifier out of credits,
--                                        Companies House rate-limited)   -> not a verdict
--
-- Rows 3 and 4 are our problem, not the lead's, and `discarded` is terminal
-- (states.TERMINAL, ALLOWED[DISCARDED] = {}), so a paid-for lead was destroyed by a
-- regex false positive. Three of the five real draft discards on this database were a
-- subject line being one character too long. At autonomous rates that is ~15 leads a day.
--
-- PARKED is deliberately in NEITHER set: not CONTACTABLE (nothing drafts or sends it)
-- and not TERMINAL (a repair pass can re-admit it). `discarded` itself stays terminal —
-- SUPPRESSED and BOUNCED must be irreversible, and loosening the whole partition to fix
-- one member would weaken the invariant that matters most.
--
-- park_count bounds the retry: three parks and the lead really is discarded, so parking
-- can never become an infinite requeue loop.
--
-- NOTE: this migration only ADDS the enum value. Postgres forbids using a new enum value
-- in the same transaction that added it, and migrate.py runs one file per transaction —
-- so anything that WRITES 'parked' must live in a later migration.

alter type outreach.lead_state add value if not exists 'parked';

alter table outreach.leads add column if not exists parked_reason text;
alter table outreach.leads add column if not exists parked_at     timestamptz;
alter table outreach.leads add column if not exists park_count    int not null default 0;

comment on column outreach.leads.parked_reason is
  'Why the pipeline could not finish this lead (machinery failure or absent evidence) — never a verdict about the business.';
comment on column outreach.leads.park_count is
  'Times parked. At PARK_MAX the lead is discarded for real, so retry is bounded.';
