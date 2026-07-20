-- outreach-build · migration 0009 — manual overrides + company research profiles
--
-- Three additions, all idempotent:
--
-- 1. drafts.outbox_at — a manual "send now" drops the draft into an OUTBOX with an
--    undo window instead of sending inline. NULL = not in the outbox. Cancelling
--    clears it and the draft keeps its original queue slot, so an undo is a true
--    no-op rather than a re-queue.
--
-- 2. profiles — the CRM layer: structured research per company. Deliberately jsonb
--    and NOT generated HTML. Stored markup can't be queried ("which leads take card
--    already?"), can't be re-rendered when the layout changes, and the drafter needs
--    these as DATA — the hooks feed straight into the email prompt. HTML is a
--    rendering of this table, never the storage for it.
--
-- 3. domain columns — manual research must answer "do we already have this company?"
--    BEFORE spending anything on it, and that lookup is by website domain. Backfilled
--    from the websites already on file.

-- ---- 1. outbox ----
alter table outreach.drafts add column if not exists outbox_at timestamptz;
-- partial: the sweeper polls this every few seconds and the outbox is nearly always empty
create index if not exists drafts_outbox_idx on outreach.drafts (outbox_at)
  where outbox_at is not null;

-- ---- 2. company research profiles ----
create table if not exists outreach.profiles (
  company_number  text primary key references outreach.leads(company_number) on delete cascade,
  domain          text,
  facts           jsonb not null default '{}'::jsonb,  -- structured research (see research.py)
  sources         jsonb not null default '[]'::jsonb,  -- [{kind, ref}] provenance per fact set
  research_source text,                                -- 'manual' | 'pipeline'
  researched_at   timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists profiles_domain_idx on outreach.profiles (domain);

-- ---- 3. domain (dedupe key) ----
alter table outreach.enrichment add column if not exists domain text;
alter table outreach.leads      add column if not exists domain text;

-- backfill: strip scheme + www + path, lowercase. Same rule as research.normalise_domain,
-- which is what every future write uses — keep the two in step if either changes.
update outreach.enrichment set domain =
  lower(split_part(regexp_replace(website, '^https?://(www\.)?', '', 'i'), '/', 1))
  where website is not null and website <> '' and domain is null;

update outreach.leads set domain =
  lower(split_part(regexp_replace(registered_address->>'website', '^https?://(www\.)?', '', 'i'), '/', 1))
  where registered_address->>'website' is not null
    and registered_address->>'website' <> '' and domain is null;

create index if not exists enrichment_domain_idx on outreach.enrichment (domain);
create index if not exists leads_domain_idx      on outreach.leads (domain);
