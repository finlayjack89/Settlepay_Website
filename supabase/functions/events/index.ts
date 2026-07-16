// `events` Edge Function — first-party, cookieless analytics beacon.
//
// Receives navigator.sendBeacon() POSTs from the site and stores aggregate
// pageview/funnel events in public.site_events. Privacy: no cookies client-side;
// no IP or user-agent stored — only a one-way hash of (IP, UA, day salt) that
// rotates daily, so visitors cannot be tracked across days or identified.
// Public endpoint: deploy with `--no-verify-jwt` (beacons carry no auth header).
//
// Env (function secrets):
//   EVENTS_SALT      secret mixed into the visitor hash (any long random string)
//   ALLOWED_ORIGIN   CORS origin to allow (default "*"; set to https://settlepay.uk in prod)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';

const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type',
};

// Only events the site actually emits — anything else is dropped, so the
// table cannot be polluted by junk POSTs.
const EVENTS = new Set([
  'pageview',
  'enquiry_open',
  'enquiry_submitted',
  'booking_view',
  'booking_slot_selected',
  'booking_details_submitted',
  'booking_confirmed',
  'preview_generate',
  'preview_share_created',
  'preview_download',
]);

const ok = () => new Response(null, { status: 204, headers: cors });

async function visitorHash(req: Request): Promise<string | null> {
  const ip = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ?? '';
  const ua = req.headers.get('user-agent') ?? '';
  if (!ip && !ua) return null;
  const salt = Deno.env.get('EVENTS_SALT') ?? 'settlepay-events';
  const day = new Date().toISOString().slice(0, 10); // daily rotation
  const data = new TextEncoder().encode(`${salt}|${day}|${ip}|${ua}`);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(digest).slice(0, 12))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}

const clip = (v: unknown, max: number): string | null =>
  typeof v === 'string' && v ? v.slice(0, max) : null;

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return ok(); // beacons never read the response

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return ok();
  }

  const event = typeof body.event === 'string' ? body.event : '';
  if (!EVENTS.has(event)) return ok();

  // Referrer: keep the external host only — never full URLs, never same-site.
  let referrer: string | null = null;
  if (event === 'pageview' && typeof body.ref === 'string' && body.ref) {
    try {
      const host = new URL(body.ref).hostname;
      if (host && !host.endsWith('settlepay.uk') && host !== 'localhost') referrer = host.slice(0, 120);
    } catch { /* unparseable referrer — drop it */ }
  }

  const props =
    body.props && typeof body.props === 'object' && !Array.isArray(body.props)
      ? JSON.parse(JSON.stringify(body.props).slice(0, 2000))
      : null;

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  const { error } = await supabase.from('site_events').insert({
    event,
    path: clip(body.path, 200),
    source: clip(body.source, 80),
    referrer,
    visitor: await visitorHash(req),
    props,
  });
  if (error) console.error('event insert failed:', error);

  return ok();
});
