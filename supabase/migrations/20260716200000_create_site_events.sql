-- Migration: create the `site_events` table — first-party, cookieless analytics.
--
-- Privacy model (UK GDPR / PECR — see /privacy/ and /cookies/):
--   * NO cookies or device storage are used to collect this data.
--   * NO IP address or raw user-agent is ever stored. The `visitor` column is
--     a one-way SHA-256 hash of (IP, user-agent, day-salt) computed in the
--     `events` Edge Function; the salt rotates daily, so the hash cannot link
--     a visitor across days and cannot be reversed to identify anyone.
--   * Aggregate measurement only: pageviews and named funnel events
--     (enquiry_open, booking steps, preview generations).
--
-- Access model: the `events` Edge Function writes with the service-role key
-- (bypasses RLS). RLS is enabled with NO policies — anon/authenticated clients
-- have zero access.

create table if not exists public.site_events (
  id          bigint      generated always as identity primary key,
  created_at  timestamptz not null default now(),
  event       text        not null,
  path        text,
  source      text,           -- which button/section triggered a funnel event
  referrer    text,           -- external referrer host on pageviews, else null
  visitor     text,           -- day-salted anonymous hash (see header comment)
  props       jsonb
);

comment on table public.site_events is
  'First-party cookieless site analytics. Aggregate funnel measurement only; visitor hashes rotate daily and identify no one. Retention: prune rows older than 13 months.';

create index if not exists site_events_created_idx on public.site_events (created_at);
create index if not exists site_events_event_idx   on public.site_events (event, created_at);

alter table public.site_events enable row level security;
