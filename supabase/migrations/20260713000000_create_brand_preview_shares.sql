-- Migration: `brand_preview_shares` — shareable preview pages (settlepay.uk/p/<slug>).
-- One row per share: an unguessable slug + a server-side SNAPSHOT of the
-- generated design (never client-supplied — the share page renders only
-- pipeline-validated content). Written/read ONLY by the brand-preview function
-- via the service-role key; RLS enabled with no policies.

create table if not exists public.brand_preview_shares (
  slug        text        primary key,
  domain      text        not null,
  snapshot    jsonb       not null,   -- { name, domain, brand, variant:{brief,tokens,logo} }
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null default now() + interval '30 days',
  views       integer     not null default 0
);

comment on table public.brand_preview_shares is
  'Shareable /p/<slug> preview pages. Snapshot is copied server-side from the generation cache at share time. Expired rows purged nightly. No personal data.';

alter table public.brand_preview_shares enable row level security;

-- Atomic view counter (supabase-js update() cannot express views = views + 1).
create or replace function public.bump_share_views(share_slug text)
returns void
language sql
as $$
  update public.brand_preview_shares set views = views + 1 where slug = share_slug;
$$;

revoke execute on function public.bump_share_views(text) from public, anon, authenticated;

-- Fold expired shares into the nightly purge.
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
    delete from public.brand_preview_shares where expires_at < now();
  $$
);
