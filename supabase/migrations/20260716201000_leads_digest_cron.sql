-- Migration: schedule the daily unactioned-leads digest.
--
-- pg_cron pings the `leads-digest` Edge Function every morning; the function
-- emails the owner ONLY if leads have sat in status 'new' for over 24 hours
-- (its own throttle bounds it to one email per 20h). This is the safety net
-- for silent enquiry-notification failure — see supabase/functions/leads-digest.
--
-- Uses pg_net for the HTTP call (enable via dashboard if the extension create
-- fails here). The function URL is public information; the function needs no
-- auth because it can only ever send one bounded digest to the owner.

create extension if not exists pg_net;

do $$
begin
  if exists (select 1 from cron.job where jobname = 'leads-digest') then
    perform cron.unschedule('leads-digest');
  end if;
end;
$$;

select cron.schedule(
  'leads-digest',
  '5 8 * * *',  -- daily at 08:05 UTC (morning UK)
  $$
  select net.http_post(
    url    := 'https://xqpbcoldcqfxfwhcqlcy.supabase.co/functions/v1/leads-digest',
    body   := '{}'::jsonb,
    headers := '{"content-type": "application/json"}'::jsonb
  );
  $$
);
