-- outreach-build · migration 0020 — campaigns you can aim, and schedules you can edit
--
-- (a) CAMPAIGNS. The discovery grid is ~14,700 queries swept by ONE global cursor, and
--     the credit runs out long before the grid does — so the cursor's position decides
--     what is ever discovered, and there was no way to say "go and work auctioneers in
--     Yorkshire" without dragging the scheduled sweep off course. A campaign is a named
--     slice of that grid with its OWN cursor and its own target, so an operator can aim a
--     run, watch it fill, and pause it, while the global sweep carries on untouched.
--
-- (b) SCHEDULES. The only cadence in this system is a Cloud Scheduler cron hitting /tick
--     every 10 minutes, which lives in GCP and cannot be seen or changed from the console.
--     Anything else that should happen regularly — calibrate the critic weekly, refresh
--     stale facts nightly — had no home. These rows ride the existing tick rather than
--     adding a second cron: the schedule then lives in the database, where the dashboard
--     can edit it, and there is still exactly one thing in GCP to keep alive.

create table if not exists outreach.campaigns (
  id             bigint generated always as identity primary key,
  name           text not null unique,
  -- the slice, as the names the console offers (targeting.PLACES_VERTICAL_GROUPS /
  -- PLACES_REGIONS). Stored as the OPERATOR's words, not as an expanded query list: the
  -- grid changes as verticals are added, and a campaign should follow it rather than
  -- freeze a copy that silently stops matching.
  vertical       text not null default 'all',
  region         text not null default 'all',
  target         int  not null default 100,       -- corporate leads wanted
  found          int  not null default 0,         -- cleared the PECR gate under this campaign
  status         text not null default 'active'
                   check (status in ('active', 'paused', 'done')),
  -- Its own cursor into its own slice. Sharing the global one would either skip most of
  -- the campaign's ground or drag the scheduled sweep off course.
  cursor_key     text not null,
  created_by     text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists campaigns_active_idx on outreach.campaigns(status)
  where status = 'active';

-- Which campaign a lead came from, so "found" is a COUNT rather than a tally that drifts.
-- Nullable: every lead discovered by the scheduled sweep has no campaign, and that is the
-- normal case rather than missing data.
alter table outreach.leads add column if not exists campaign_id bigint
  references outreach.campaigns(id) on delete set null;
create index if not exists leads_campaign_idx on outreach.leads(campaign_id)
  where campaign_id is not null;

create table if not exists outreach.schedules (
  id             bigint generated always as identity primary key,
  kind           text not null,                   -- a jobs.REGISTRY task
  params         jsonb not null default '{}'::jsonb,
  every_minutes  int  not null check (every_minutes >= 10),
  enabled        boolean not null default true,
  last_run_at    timestamptz,
  next_run_at    timestamptz not null default now(),
  created_by     text,
  created_at     timestamptz not null default now()
);
-- The tick asks "what is due" on every run, so this is the index that matters.
create index if not exists schedules_due_idx on outreach.schedules(next_run_at)
  where enabled;

comment on column outreach.schedules.every_minutes is
  'Minimum gap between runs. Floored at 10 because the tick itself only fires every 10 '
  'minutes — a smaller number would promise a cadence the scheduler cannot deliver.';
