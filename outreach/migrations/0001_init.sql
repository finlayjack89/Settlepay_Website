-- outreach-build · migration 0001 — Foundations (phase A)
-- Creates the pipeline's OWN schema. NEVER touches the website's public tables
-- (public.leads = live inbound enquiries). Idempotent: safe to re-run.

create schema if not exists outreach;

-- ---- enums ----
do $$ begin
  create type outreach.subscriber_class as enum ('corporate','individual','unknown');
exception when duplicate_object then null; end $$;

do $$ begin
  create type outreach.lead_state as enum (
    'discovered','enriched','drafted','awaiting_approval','approved',
    'sending','sent','replied',                 -- contactable
    'suppressed','rejected','discarded','bounced' -- terminal / non-contactable
  );
exception when duplicate_object then null; end $$;

-- ---- leads (OUTBOUND cold leads from Companies House) ----
create table if not exists outreach.leads (
  id                 uuid primary key default gen_random_uuid(),
  company_number     text unique not null,
  company_name       text not null,
  company_status     text,
  company_type       text,
  sic_codes          text[],
  registered_address jsonb,
  subscriber_class   outreach.subscriber_class,
  state              outreach.lead_state not null default 'discovered',
  source             text not null default 'companies_house_advanced_search',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);
create index if not exists leads_state_idx on outreach.leads(state);

-- ---- enrichment (website, contact email, verification, LLM signal) ----
create table if not exists outreach.enrichment (
  id                 uuid primary key default gen_random_uuid(),
  company_number     text not null unique references outreach.leads(company_number) on delete cascade,
  website            text,
  contact_email      text,
  email_verified     boolean,
  email_verify_result text,
  signal             text,
  scraped            jsonb,
  created_at         timestamptz not null default now()
);
create index if not exists enrichment_email_idx on outreach.enrichment(lower(contact_email));

-- ---- drafts (body_original IMMUTABLE; body_final after human edit) ----
create table if not exists outreach.drafts (
  id             uuid primary key default gen_random_uuid(),
  company_number text not null references outreach.leads(company_number) on delete cascade,
  subject        text,
  body_original  text not null,                         -- AI draft; never mutated
  body_final     text,                                  -- human-edited / approved copy
  reviewer_note  text,
  prompt_version text,
  status         text not null default 'awaiting_approval'
                   check (status in ('awaiting_approval','approved','rejected','sent')),
  decided_by     text,
  decided_at     timestamptz,
  created_at     timestamptz not null default now()
);
create index if not exists drafts_status_idx on outreach.drafts(status);

-- ---- sends (dry_run by default; live is hard-gated behind G-SEND) ----
create table if not exists outreach.sends (
  id                  uuid primary key default gen_random_uuid(),
  draft_id            uuid references outreach.drafts(id) on delete set null,
  company_number      text,
  to_email            text,
  mode                text not null default 'dry_run' check (mode in ('dry_run','live')),
  status              text,
  provider_message_id text,
  error               text,
  created_at          timestamptz not null default now()
);

-- ---- replies / bounces / complaints / unsubscribes ----
create table if not exists outreach.replies (
  id             uuid primary key default gen_random_uuid(),
  company_number text,
  from_email     text,
  kind           text,   -- reply | bounce | complaint | unsubscribe
  raw            jsonb,
  received_at    timestamptz not null default now()
);

-- ---- suppressions (PECR + opt-outs + bounces) ----
create table if not exists outreach.suppressions (
  id             uuid primary key default gen_random_uuid(),
  email          text,
  domain         text,
  company_number text,
  reason         text not null,
  created_at     timestamptz not null default now()
);
create index if not exists suppressions_email_idx on outreach.suppressions(lower(email));
create index if not exists suppressions_domain_idx on outreach.suppressions(lower(domain));

-- ---- audit_log (one row per lead decision: source + lawful_basis + reason) ----
create table if not exists outreach.audit_log (
  id             bigint generated always as identity primary key,
  company_number text,
  event          text not null,
  source         text,
  lawful_basis   text,
  reason         text,
  detail         jsonb,
  created_at     timestamptz not null default now()
);
create index if not exists audit_company_idx on outreach.audit_log(company_number);
