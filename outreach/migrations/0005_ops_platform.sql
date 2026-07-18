-- 0005 — ops platform: jobs queue/history, provider-agnostic spend ledger,
-- operational flags (DB kill switch), touch-2 follow-ups, fine-tuning telemetry,
-- integration provenance seam. Idempotent, style of 0001-0004.

set search_path to outreach, public;

-- jobs: single table = execution queue (JobRunner claims queued rows with
-- FOR UPDATE SKIP LOCKED) + history the dashboard reads. A tick job stores its
-- full per-stage summary in result.
create table if not exists outreach.jobs (
  id             bigint generated always as identity primary key,
  kind           text not null,
  params         jsonb not null default '{}'::jsonb,
  status         text not null default 'queued'
                   check (status in ('queued','running','succeeded','failed','cancelled')),
  progress       jsonb not null default '{}'::jsonb,   -- {done,total,log:[{t,msg}]}
  result         jsonb,
  error          text,
  requested_by   text not null default 'system',       -- 'scheduler' | login user | 'cli'
  created_at     timestamptz not null default now(),
  started_at     timestamptz,
  finished_at    timestamptz
);
create index if not exists jobs_active_idx  on outreach.jobs (status) where status in ('queued','running');
create index if not exists jobs_created_idx on outreach.jobs (created_at desc);

-- spend: one ledger for every paid provider (anthropic tokens, millionverifier
-- verifies, clay credits later). The monthly cap gate reads month_total from here.
create table if not exists outreach.spend (
  id             bigint generated always as identity primary key,
  provider       text not null,
  purpose        text,
  model          text,
  units_in       bigint not null default 0,
  units_out      bigint not null default 0,
  cost_gbp       numeric(12,6) not null default 0,
  detail         jsonb,
  job_id         bigint,
  company_number text,
  created_at     timestamptz not null default now()
);
create index if not exists spend_created_idx on outreach.spend (created_at);

-- ops_flags: DB-backed operational overrides (kill_switch, digest date-throttle).
-- env KILL_SWITCH remains the hard override; DB read failure fails open to env.
create table if not exists outreach.ops_flags (
  key        text primary key,
  value      text,
  reason     text,
  updated_by text,
  updated_at timestamptz not null default now()
);

-- touch-2 follow-ups + fine-tuning telemetry + integration provenance seam
alter table outreach.drafts     add column if not exists touch int not null default 1;
alter table outreach.drafts     add column if not exists parent_draft_id uuid references outreach.drafts(id);
alter table outreach.drafts     add column if not exists edit_ratio real;  -- 0.0 = approved untouched
create index if not exists drafts_company_touch_idx on outreach.drafts (company_number, touch);
alter table outreach.enrichment add column if not exists provenance jsonb;
