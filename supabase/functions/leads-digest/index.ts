// `leads-digest` Edge Function — the safety net for silent notification failure.
//
// If enquiry notifications ever stop arriving (Resend outage, config drift),
// leads would sit unactioned with nobody the wiser. A daily pg_cron job pings
// this function; if any lead has been in status 'new' for more than 24 hours,
// it emails ONE digest to the owner. Bounded and self-throttling: it refuses
// to send more than one digest per 20 hours (marker row in site_events, using
// an event name the public beacon's allowlist can never accept), so even
// spam-triggering the endpoint cannot flood the inbox.
//
// Env (project secrets — same ones the enquiry function already uses):
//   RESEND_API_KEY, LEAD_NOTIFY_TO, LEAD_NOTIFY_FROM
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.
// Deploy with `--no-verify-jwt` (the cron trigger carries no auth header).

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const json = (body: unknown, status = 200): Response =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

Deno.serve(async (req) => {
  if (req.method !== 'POST' && req.method !== 'GET') return json({ error: 'method-not-allowed' }, 405);

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  // Self-throttle: at most one digest per 20h, regardless of who calls us.
  const throttleSince = new Date(Date.now() - 20 * 3600_000).toISOString();
  const { count: sentRecently } = await supabase
    .from('site_events')
    .select('id', { count: 'exact', head: true })
    .eq('event', 'leads_digest_sent')
    .gte('created_at', throttleSince);
  if ((sentRecently ?? 0) > 0) return json({ ok: true, skipped: 'throttled' });

  const staleBefore = new Date(Date.now() - 24 * 3600_000).toISOString();
  const { data: stale, error } = await supabase
    .from('leads')
    .select('id, business, name, created_at')
    .eq('status', 'new')
    .lt('created_at', staleBefore)
    .order('created_at', { ascending: true })
    .limit(20);
  if (error) return json({ error: 'query-failed' }, 500);
  if (!stale || stale.length === 0) return json({ ok: true, stale: 0 });

  const key = Deno.env.get('RESEND_API_KEY');
  const to = Deno.env.get('LEAD_NOTIFY_TO');
  const from = Deno.env.get('LEAD_NOTIFY_FROM');
  if (!key || !to || !from) return json({ error: 'not-configured' }, 503);

  const rows = stale
    .map((l) => {
      const age = Math.round((Date.now() - new Date(l.created_at).getTime()) / 3600_000);
      return `• ${l.business} (${l.name}) — waiting ${age}h`;
    })
    .join('\n');
  const text =
    `${stale.length} enquiry(ies) have sat in status 'new' for more than 24 hours.\n\n` +
    `${rows}\n\nIf notifications normally arrive fine, this may mean the enquiry ` +
    `notification email is failing silently — check the Resend logs.\n\n— SettlePay leads digest`;

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'content-type': 'application/json' },
    body: JSON.stringify({
      from,
      to: [to],
      subject: `Unactioned enquiries: ${stale.length} waiting over 24h`,
      text,
    }),
  });
  if (!res.ok) {
    console.error('digest send failed:', res.status, await res.text());
    return json({ error: 'send-failed' }, 500);
  }

  await supabase.from('site_events').insert({ event: 'leads_digest_sent', props: { stale: stale.length } });
  return json({ ok: true, stale: stale.length });
});
