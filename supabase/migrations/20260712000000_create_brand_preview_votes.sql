-- Migration: `brand_preview_votes` — the "prefer this design" tally for the
-- /preview/ model split test. Written ONLY by the brand-preview function via the
-- service-role key; RLS enabled with no policies (zero anon access), matching
-- the other brand-preview tables.

create table if not exists public.brand_preview_votes (
  id           uuid        primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  domain       text        not null,
  variant_key  text        not null,   -- provider registry key: haiku|sonnet|luna|terra
  model        text        not null,   -- exact model id at vote time
  ip_hash      text                    -- salted SHA-256 of the IP; never the raw IP
);

comment on table public.brand_preview_votes is
  'Model split-test preferences from the /preview/ tool. One row per "prefer this design" click. No personal data (salted IP hash only).';

create index if not exists brand_preview_votes_key_idx
  on public.brand_preview_votes (variant_key, created_at desc);

alter table public.brand_preview_votes enable row level security;

-- Fold votes into the nightly purge (votes kept 90 days — they ARE the test data).
do $$
begin
  if exists (select 1 from cron.job where jobname = 'purge-brand-preview') then
    perform cron.unschedule('purge-brand-preview');
  end if;
end;
$$;

select cron.schedule(
  'purge-brand-preview',
  '23 3 * * *',  -- daily at 03:23 UTC
  $$
    delete from public.brand_previews where fetched_at < now() - interval '30 days';
    delete from public.brand_preview_requests where created_at < now() - interval '2 days';
    delete from public.brand_preview_votes where created_at < now() - interval '90 days';
  $$
);
