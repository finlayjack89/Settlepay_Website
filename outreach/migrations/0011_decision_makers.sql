-- outreach-build · migration 0011 — decision-maker sourcing (Companies House officers)
--
-- Moving outreach from role addresses (info@ — not personal data) to NAMED individuals
-- (personal data, full UK GDPR). Two stores, both idempotent:
--
-- 1. officers — directors/members from the Companies House public register, per company.
--    Deliberately MINIMISED: name + role + appointment date only. Companies House also
--    returns a partial date of birth and a correspondence address; we store NEITHER.
--    We need to know WHO runs the business and infer ONE work email — nothing else, so
--    nothing else is kept (data minimisation, UK GDPR art. 5(1)(c)).
--
-- 2. enrichment.contact_name — when the resolved contact is a named person rather than a
--    role mailbox, this is who it is. contact_tier gains a 'named' value (the column is
--    free-text, so no enum change) that ranks above 'verified'; send.py prefers it.
--
-- The lawful basis for holding and using this is legitimate interests, recorded on every
-- officer row via the audit_log the same way every other lead decision is. The art. 14
-- transparency duty (tell the person, within ~a month, where we got their details) is
-- discharged at first contact by the named-send email footer — see emailfmt.py.

create table if not exists outreach.officers (
  id             uuid primary key default gen_random_uuid(),
  company_number text not null references outreach.leads(company_number) on delete cascade,
  name           text not null,               -- as the register holds it: "SMITH, John Andrew"
  role           text,                         -- director | llp-member | member | ...
  appointed_on   date,
  source         text not null default 'companies_house',
  created_at     timestamptz not null default now(),
  unique (company_number, name, role)          -- re-fetching a company is a no-op
);
create index if not exists officers_company_idx on outreach.officers (company_number);

alter table outreach.enrichment add column if not exists contact_name text;

-- When a decision-maker email lookup COMPLETED (all permutations checked, or a catch-all
-- domain skipped) — NOT when it was deferred by a verifier outage. This is what stops the
-- lookup being retried (and re-billing MillionVerifier) every tick once it has genuinely
-- finished, WITHOUT stranding a lead whose only 'completion' was the verifier being down:
-- a deferred lead leaves this null and is retried next tick. Same shape as
-- leads.crossref_checked_at.
alter table outreach.enrichment add column if not exists dm_attempted_at timestamptz;
