// `book` — public, browser-facing (deploy --no-verify-jwt).
// Reserves the slot (DB unique index = atomic lock), creates a Google Calendar
// event WITH a Meet link (sendUpdates:'none' so Google emails nobody), stores the
// booking, and sends ONE SettlePay-branded confirmation with an .ics attachment.
//
// Env: GOOGLE_SA_KEY (real calendar; unset = mock), RESEND_API_KEY,
//      BOOKING_CONFIRM_FROM | LEAD_AUTOREPLY_FROM (sender), ALLOWED_ORIGIN, SITE_URL.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { BOOKING_CONFIG } from './_config.ts';
import { generateSlots } from './_slots.ts';
import { makeCalendarClient } from './_calendar.ts';
import { buildIcs } from './_ics.ts';
import { renderBookingConfirmation } from './templates.ts';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';
const SITE_URL = Deno.env.get('SITE_URL') ?? 'https://settlepay.uk';
const TZ = BOOKING_CONFIG.timeZone;
const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept',
};
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, 'content-type': 'application/json' } });
}
const str = (v: unknown) => (typeof v === 'string' ? v.trim() : '');

function formatWhen(iso: string): { date: string; time: string } {
  const d = new Date(iso);
  return {
    date: new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: TZ }).format(d),
    time: new Intl.DateTimeFormat('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: TZ }).format(d),
  };
}
const b64utf8 = (s: string) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));

async function sendConfirmation(row: { id: string; manage_token: string }, v: {
  email: string; name: string; startIso: string; endIso: string; meetUrl: string; business: string;
}): Promise<void> {
  const from = Deno.env.get('BOOKING_CONFIRM_FROM') ?? Deno.env.get('LEAD_AUTOREPLY_FROM');
  const key = Deno.env.get('RESEND_API_KEY');
  if (!from || !key) { console.warn('email sender/key not set — skipping confirmation'); return; }
  const { date, time } = formatWhen(v.startIso);
  const firstName = v.name.split(/\s+/)[0] || 'there';
  const manageUrl = `${SITE_URL}/manage/?t=${row.manage_token}`;
  const { html, text } = renderBookingConfirmation({ first_name: firstName, date, time, join_url: v.meetUrl, manage_url: manageUrl });
  const ics = buildIcs({
    uid: `${row.id}@settlepay.uk`, start: v.startIso, end: v.endIso, dtstamp: new Date(),
    summary: 'SettlePay consultation with Finlay',
    description: `Your free consultation with Finlay Salisbury (SettlePay).\\nJoin: ${v.meetUrl}`,
    organizerName: 'Finlay Salisbury', organizerEmail: 'hello@settlepay.uk',
    attendeeName: v.name, attendeeEmail: v.email,
  });
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify({
        from, to: [v.email], subject: 'Your SettlePay consultation is confirmed', html, text,
        attachments: [{ filename: 'settlepay-consultation.ics', content: b64utf8(ics), content_type: 'text/calendar' }],
      }),
    });
    if (!res.ok) console.error('confirmation send failed:', res.status, await res.text());
  } catch (e) {
    console.error('confirmation error:', e);
  }
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: 'invalid-json' }, 400); }
  if (str(body._gotcha)) return json({ ok: true }); // honeypot

  const startIso = str(body.start);
  const name = str(body.name);
  const email = str(body.email);
  const business = str(body.business);
  const notes = str(body.notes);
  const timezone = str(body.timezone) || TZ;
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  const startMs = Date.parse(startIso);
  if (!name || !emailOk || !startIso || Number.isNaN(startMs)) {
    return json({ error: 'validation', detail: 'Missing or invalid fields.' }, 400);
  }
  const endIso = new Date(startMs + BOOKING_CONFIG.slotMinutes * 60000).toISOString();
  const now = new Date();
  const client = makeCalendarClient();

  // Server-side re-authorisation: the requested slot must be a currently-available
  // slot (working hours + notice + horizon + not busy). Never trust the client.
  try {
    const timeMax = new Date(now.getTime() + (BOOKING_CONFIG.horizonDays + 1) * 86400000).toISOString();
    const busy = await client.freeBusy(now.toISOString(), timeMax);
    const supabaseRead = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);
    const { data } = await supabaseRead.from('bookings').select('start_at, end_at')
      .in('status', ['confirmed', 'rescheduled']).gte('start_at', now.toISOString()).lte('start_at', timeMax);
    for (const b of data ?? []) if (b.start_at && b.end_at) busy.push({ start: b.start_at, end: b.end_at });
    const ok = generateSlots(BOOKING_CONFIG, busy, now).some((s) => s.startIso === new Date(startMs).toISOString());
    if (!ok) return json({ error: 'slot-unavailable' }, 409);
  } catch (e) {
    console.error('availability re-check failed:', e);
    return json({ error: 'availability-unavailable' }, 502);
  }

  const supabase = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);

  // 1) Reserve the slot FIRST — the partial unique index is the atomic double-book lock.
  const { data: inserted, error: insErr } = await supabase.from('bookings').insert({
    source: 'google', cal_uid: null, status: 'confirmed',
    title: `SettlePay consultation — ${business || name}`,
    start_at: new Date(startMs).toISOString(), end_at: endIso,
    attendee_name: name, attendee_email: email, attendee_timezone: timezone,
    raw: { business, notes, via: 'bespoke' },
  }).select('id, manage_token').single();
  if (insErr) {
    if ((insErr as any).code === '23505') return json({ error: 'slot-taken' }, 409);
    console.error('booking insert failed:', insErr);
    return json({ error: 'store-failed' }, 500);
  }

  // 2) Create the Google event + Meet. If it fails, release the slot (delete the row).
  let meetUrl = '';
  try {
    const ev = await client.createEvent({
      startIso: new Date(startMs).toISOString(), endIso, timeZone: timezone,
      summary: `SettlePay consultation — ${name}${business ? ` (${business})` : ''}`,
      description: `Free consultation booked via settlepay.uk.\n\nName: ${name}\nEmail: ${email}${business ? `\nBusiness: ${business}` : ''}${notes ? `\n\nNotes: ${notes}` : ''}`,
      attendeeName: name, attendeeEmail: email, requestId: inserted.id,
    });
    meetUrl = ev.meetUrl;
    await supabase.from('bookings').update({ google_event_id: ev.eventId, join_url: meetUrl }).eq('id', inserted.id);
  } catch (e) {
    console.error('createEvent failed, releasing slot:', e);
    await supabase.from('bookings').delete().eq('id', inserted.id);
    return json({ error: 'calendar-failed' }, 502);
  }

  // 3) Branded confirmation email + .ics (best-effort; never fails the booking).
  await sendConfirmation(inserted, { email, name, startIso: new Date(startMs).toISOString(), endIso, meetUrl, business });

  const { date, time } = formatWhen(new Date(startMs).toISOString());
  return json({
    ok: true, meetUrl, date, time,
    start: new Date(startMs).toISOString(), end: endIso,
    manageUrl: `${SITE_URL}/manage/?t=${inserted.manage_token}`,
  });
});
