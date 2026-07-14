// `availability` — public, browser-facing (deploy --no-verify-jwt).
// Returns bookable 30-min slots = the host's working windows MINUS Google Calendar
// busy time MINUS existing bookings, grouped by London date. Read-only; no migration
// needed. Uses the mock calendar client automatically when GOOGLE_SA_KEY is unset.
//
// Env: GOOGLE_SA_KEY (real calendar; unset = mock), ALLOWED_ORIGIN. SUPABASE_URL /
// SUPABASE_SERVICE_ROLE_KEY are injected automatically.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { BOOKING_CONFIG } from './_config.ts';
import { generateSlots } from './_slots.ts';
import { makeCalendarClient, isMockCalendar } from './_calendar.ts';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';
const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept',
};
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, 'content-type': 'application/json' } });
}

const TZ = BOOKING_CONFIG.timeZone;
const partsIn = (iso: string, opts: Intl.DateTimeFormatOptions) =>
  Object.fromEntries(new Intl.DateTimeFormat('en-GB', { timeZone: TZ, ...opts }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
const timeLabel = (iso: string) => {
  const p = partsIn(iso, { hour: '2-digit', minute: '2-digit', hour12: false });
  return `${p.hour}:${p.minute}`;
};
const dayLabel = (iso: string) => {
  const p = partsIn(iso, { weekday: 'short', day: 'numeric', month: 'short' });
  return `${p.weekday} ${p.day} ${p.month}`;
};
const dateKey = (iso: string) => {
  const p = partsIn(iso, { year: 'numeric', month: '2-digit', day: '2-digit' });
  return `${p.year}-${p.month}-${p.day}`;
};

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'GET' && req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  const now = new Date();
  const timeMin = now.toISOString();
  const timeMax = new Date(now.getTime() + (BOOKING_CONFIG.horizonDays + 1) * 86400000).toISOString();

  // Busy from the host's Google Calendar…
  let busy;
  try {
    busy = await makeCalendarClient().freeBusy(timeMin, timeMax);
  } catch (e) {
    console.error('freeBusy failed:', e);
    return json({ error: 'availability-unavailable' }, 502);
  }

  // …plus existing bookings (closes FreeBusy propagation lag; only reads columns
  // that predate the google migration, so this works before it is applied).
  try {
    const supabase = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);
    const { data } = await supabase
      .from('bookings')
      .select('start_at, end_at')
      .in('status', ['confirmed', 'rescheduled'])
      .gte('start_at', timeMin)
      .lte('start_at', timeMax);
    for (const b of data ?? []) if (b.start_at && b.end_at) busy.push({ start: b.start_at, end: b.end_at });
  } catch (e) {
    console.error('db busy merge failed (continuing):', e);
  }

  const byDay = new Map<string, { start: string; end: string; label: string }[]>();
  for (const s of generateSlots(BOOKING_CONFIG, busy, now)) {
    const k = dateKey(s.startIso);
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k)!.push({ start: s.startIso, end: s.endIso, label: timeLabel(s.startIso) });
  }
  const days = [...byDay.entries()].map(([date, slots]) => ({ date, label: dayLabel(slots[0].start), slots }));

  return json({ timezone: TZ, slotMinutes: BOOKING_CONFIG.slotMinutes, mock: isMockCalendar(), days });
});
