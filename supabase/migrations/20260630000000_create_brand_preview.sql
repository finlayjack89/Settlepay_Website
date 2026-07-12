-- Migration: support tables for the `brand-preview` Edge Function (/preview/ tool).
--
-- Two tables, both written ONLY by the brand-preview function via the
-- service-role key (which bypasses RLS). RLS is enabled with no policies, so
-- anon/authenticated clients have zero access.
--
--   brand_previews          — cache of extracted brand profiles, keyed by domain,
--                             so repeat lookups don't re-bill Brandfetch/Claude.
--                             Holds only public brand data (logo, colour, font,
--                             name) + generated microcopy. No personal data.
--   brand_preview_requests  — minimal rate-limit log. Stores a salted HASH of the
--                             requester IP (never the raw IP) + the domain tried,
--                             so we can throttle abuse and gauge interest.

create extension if not exists pgcrypto;

-- ---- cache -----------------------------------------------------------------
create table if not exists public.brand_previews (
  domain      text        primary key,
  profile     jsonb       not null,
  fetched_at  timestamptz not null default now()
);

comment on table public.brand_previews is
  'Cache of public brand profiles for the /preview/ tool. TTL enforced by the function (CACHE_TTL_HOURS) and a nightly purge. No personal data.';

create index if not exists brand_previews_fetched_at_idx
  on public.brand_previews (fetched_at);

alter table public.brand_previews enable row level security;

-- ---- rate-limit log --------------------------------------------------------
create table if not exists public.brand_preview_requests (
  id          uuid        primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  ip_hash     text        not null,   -- salted SHA-256 of the IP; never the raw IP
  domain      text
);

comment on table public.brand_preview_requests is
  'Salted-IP-hash request log for /preview/ rate-limiting. Short retention (purged nightly). Holds no raw IP and no personal data.';

create index if not exists brand_preview_requests_ip_time_idx
  on public.brand_preview_requests (ip_hash, created_at desc);

alter table public.brand_preview_requests enable row level security;

-- ---- nightly housekeeping --------------------------------------------------
-- Drop cache entries older than 30 days and request-log rows older than 2 days.
create extension if not exists pg_cron;

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
  $$
);
