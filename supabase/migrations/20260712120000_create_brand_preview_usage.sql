-- Migration: `brand_preview_usage` — durable per-leg token/cost telemetry for
-- the /preview/ tool (stdout logs rotate; this is the auditable record).
-- One row per model leg per generation. Written ONLY by the brand-preview
-- function via the service-role key; RLS enabled with no policies.

create table if not exists public.brand_preview_usage (
  id                uuid        primary key default gen_random_uuid(),
  created_at        timestamptz not null default now(),
  domain            text        not null,
  variant_key       text        not null,   -- provider registry key
  model             text        not null,   -- exact model id billed
  input_tokens      integer     not null,
  output_tokens     integer     not null,
  reasoning_tokens  integer,                -- OpenAI breakdown (included in output_tokens)
  ms                integer     not null,   -- leg latency
  cost_usd          numeric(10, 6) not null -- tokens x pinned per-model price at call time
);

comment on table public.brand_preview_usage is
  'Per-leg LLM spend telemetry for the /preview/ tool. cost_usd is computed from the price table pinned in providers.ts at call time. No personal data.';

create index if not exists brand_preview_usage_key_time_idx
  on public.brand_preview_usage (variant_key, created_at desc);

alter table public.brand_preview_usage enable row level security;

-- Fold usage into the nightly purge (kept 90 days, like the votes).
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
    delete from public.brand_preview_usage where created_at < now() - interval '90 days';
  $$
);
