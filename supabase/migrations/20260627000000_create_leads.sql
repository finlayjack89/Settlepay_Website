-- Migration: create the `leads` table for website consultation enquiries.
--
-- Stores enquiries submitted via the marketing site's EnquireModal.
-- Personal data held: name, business name, email, message (UK GDPR — see /privacy/).
-- Deliberately minimised: we do NOT store IP address or user-agent.
--
-- Access model: the `enquiry` Edge Function writes here using the service-role
-- key (which bypasses RLS). RLS is enabled with NO policies, so anon and
-- authenticated clients have zero access until the future CRM defines explicit
-- policies. This table is the seed of that CRM.

create extension if not exists pgcrypto;   -- for gen_random_uuid()

create table if not exists public.leads (
  id          uuid        primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  business    text        not null,
  name        text        not null,
  email       text        not null,
  message     text        not null,
  source      text        not null default 'website-enquiry',
  status      text        not null default 'new'
              check (status in ('new','contacted','quoted','won','lost','client')),
  notes       text
);

comment on table public.leads is
  'Website consultation enquiries. Retention: non-client rows are purged ~12 months after last contact (see purge-stale-leads cron job), per the Privacy Policy.';

create index if not exists leads_created_at_idx on public.leads (created_at desc);
create index if not exists leads_status_idx     on public.leads (status);
create index if not exists leads_email_idx       on public.leads (lower(email));

-- Keep updated_at fresh on every change (so retention can anchor on "last contact").
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists leads_set_updated_at on public.leads;
create trigger leads_set_updated_at
  before update on public.leads
  for each row execute function public.set_updated_at();

-- Lock the table down. Service-role (used by the Edge Function) bypasses RLS;
-- everyone else is denied because there are no policies.
alter table public.leads enable row level security;

-- ---------------------------------------------------------------------------
-- Retention (UK GDPR). The Privacy Policy promises that enquiry data from
-- people who do not become clients is deleted within ~12 months of last
-- contact. A daily pg_cron job enforces it: it removes rows last touched over
-- 12 months ago, excluding those converted to a client/won.
--
-- Requires the pg_cron extension. If `create extension pg_cron` fails here for
-- permissions, enable it once via the Supabase dashboard (Database >
-- Extensions > pg_cron) and re-run the block below.
-- ---------------------------------------------------------------------------
create extension if not exists pg_cron;

do $$
begin
  if exists (select 1 from cron.job where jobname = 'purge-stale-leads') then
    perform cron.unschedule('purge-stale-leads');
  end if;
end;
$$;

select cron.schedule(
  'purge-stale-leads',
  '17 3 * * *',  -- daily at 03:17 UTC
  $$
    delete from public.leads
    where updated_at < now() - interval '12 months'
      and status not in ('won','client')
  $$
);
