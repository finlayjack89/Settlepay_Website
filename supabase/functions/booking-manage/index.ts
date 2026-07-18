// `booking-manage` — public, browser-facing (deploy --no-verify-jwt).
// The attendee manages their booking via an unguessable manage_token (bearer
// capability from the confirmation email). GET returns a summary; POST cancels or
// reschedules — updating the Google Calendar event and sending a branded email.
//
// Env: GOOGLE_SA_KEY, RESEND_API_KEY, BOOKING_CONFIRM_FROM|LEAD_AUTOREPLY_FROM,
//      ALLOWED_ORIGIN, SITE_URL.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { BOOKING_CONFIG } from './_config.ts';
import { generateSlots } from './_slots.ts';
import { makeCalendarClient } from './_calendar.ts';
import { buildIcs } from './_ics.ts';
import { renderBookingConfirmation, renderBookingCancel } from './templates.ts';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';
const SITE_URL = Deno.env.get('SITE_URL') ?? 'https://settlepay.uk';
const TZ = BOOKING_CONFIG.timeZone;
const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept',
};
function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...cors, 'content-type': 'application/json' } });
}
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function formatWhen(iso: string) {
  const d = new Date(iso);
  return {
    date: new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: TZ }).format(d),
    time: new Intl.DateTimeFormat('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: TZ }).format(d),
  };
}
const b64utf8 = (s: string) => btoa(String.fromCharCode(...new TextEncoder().encode(s)));

async function sendEmail(payload: Record<string, unknown>) {
  const key = Deno.env.get('RESEND_API_KEY');
  const from = Deno.env.get('BOOKING_CONFIRM_FROM') ?? Deno.env.get('LEAD_AUTOREPLY_FROM');
  if (!key || !from) { console.warn('email not configured — skipping'); return; }
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST', headers: { Authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify({ from, ...payload }),
    });
    if (!res.ok) console.error('manage email failed:', res.status, await res.text());
  } catch (e) { console.error('manage email error:', e); }
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  const supabase = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!);
  const client = makeCalendarClient();

  // Resolve the token from query (GET) or body (POST).
  const url = new URL(req.url);
  let token = url.searchParams.get('t') ?? '';
  let body: any = {};
  if (req.method === 'POST') {
    try { body = await req.json(); } catch { return json({ error: 'invalid-json' }, 400); }
    token = (body.t ?? token ?? '').trim();
  }
  if (!UUID.test(token)) return json({ error: 'not-found' }, 404);

  const { data: bk } = await supabase.from('bookings')
    .select('id, status, start_at, end_at, attendee_name, attendee_email, join_url, google_event_id')
    .eq('manage_token', token).maybeSingle();
  if (!bk) return json({ error: 'not-found' }, 404);

  const when = formatWhen(bk.start_at);
  const past = Date.parse(bk.start_at) < Date.now();
  const canManage = bk.status !== 'cancelled' && !past;

  if (req.method === 'GET') {
    return json({ ok: true, status: bk.status, date: when.date, time: when.time, start: bk.start_at, meetUrl: bk.join_url, name: bk.attendee_name, canManage });
  }
  if (req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  const firstName = (bk.attendee_name ?? '').split(/\s+/)[0] || 'there';
  const action = String(body.action ?? '');

  // ---- CANCEL --------------------------------------------------------------
  if (action === 'cancel') {
    if (bk.status === 'cancelled') return json({ ok: true, status: 'cancelled' });
    if (bk.google_event_id) { try { await client.deleteEvent(bk.google_event_id); } catch (e) { console.error('deleteEvent:', e); } }
    await supabase.from('bookings').update({ status: 'cancelled' }).eq('id', bk.id);
    const { html, text } = renderBookingCancel({ first_name: firstName, date: when.date, time: when.time, rebook_url: `${SITE_URL}/book/` });
    if (bk.attendee_email) await sendEmail({ to: [bk.attendee_email], subject: 'Your SettlePay consultation is cancelled', html, text });
    return json({ ok: true, status: 'cancelled' });
  }

  // ---- RESCHEDULE ----------------------------------------------------------
  if (action === 'reschedule') {
    if (!canManage) return json({ error: 'not-manageable' }, 409);
    const startIso = String(body.start ?? '');
    const startMs = Date.parse(startIso);
    if (Number.isNaN(startMs)) return json({ error: 'validation' }, 400);
    const endIso = new Date(startMs + BOOKING_CONFIG.slotMinutes * 60000).toISOString();
    const now = new Date();

    // Validate the new slot is genuinely available.
    try {
      const timeMax = new Date(now.getTime() + (BOOKING_CONFIG.horizonDays + 1) * 86400000).toISOString();
      const busy = await client.freeBusy(now.toISOString(), timeMax);
      const { data } = await supabase.from('bookings').select('start_at, end_at')
        .in('status', ['confirmed', 'rescheduled']).neq('id', bk.id).gte('start_at', now.toISOString()).lte('start_at', timeMax);
      for (const b of data ?? []) if (b.start_at && b.end_at) busy.push({ start: b.start_at, end: b.end_at });
      if (!generateSlots(BOOKING_CONFIG, busy, now).some((s) => s.startIso === new Date(startMs).toISOString())) {
        return json({ error: 'slot-unavailable' }, 409);
      }
    } catch (e) { console.error('reschedule re-check:', e); return json({ error: 'availability-unavailable' }, 502); }

    // DB-first (atomic slot lock), then move the Google event; revert on failure.
    const prev = { start_at: bk.start_at, end_at: bk.end_at, status: bk.status };
    const { error: upErr } = await supabase.from('bookings')
      .update({ start_at: new Date(startMs).toISOString(), end_at: endIso, status: 'rescheduled' }).eq('id', bk.id);
    if (upErr) {
      if ((upErr as any).code === '23505') return json({ error: 'slot-taken' }, 409);
      return json({ error: 'store-failed' }, 500);
    }
    if (bk.google_event_id) {
      try {
        await client.updateEvent(bk.google_event_id, { startIso: new Date(startMs).toISOString(), endIso, timeZone: TZ });
      } catch (e) {
        console.error('updateEvent failed, reverting row:', e);
        await supabase.from('bookings').update(prev).eq('id', bk.id);
        return json({ error: 'calendar-failed' }, 502);
      }
    }

    const nw = formatWhen(new Date(startMs).toISOString());
    const manageUrl = `${SITE_URL}/manage/?t=${token}`;
    const { html, text } = renderBookingConfirmation({ first_name: firstName, date: nw.date, time: nw.time, join_url: bk.join_url ?? '', manage_url: manageUrl });
    const ics = buildIcs({
      uid: `${bk.id}@settlepay.uk`, start: new Date(startMs).toISOString(), end: endIso, dtstamp: new Date(), sequence: 1,
      summary: 'SettlePay consultation with Finlay', description: `Rescheduled consultation.\\nJoin: ${bk.join_url ?? ''}`,
      organizerName: 'Finlay Salisbury', organizerEmail: 'hello@settlepay.uk', attendeeName: bk.attendee_name ?? '', attendeeEmail: bk.attendee_email ?? '',
    });
    if (bk.attendee_email) await sendEmail({
      to: [bk.attendee_email], subject: 'Your SettlePay consultation has moved', html, text,
      attachments: [{ filename: 'settlepay-consultation.ics', content: b64utf8(ics), content_type: 'text/calendar' }],
    });
    return json({ ok: true, status: 'rescheduled', date: nw.date, time: nw.time, meetUrl: bk.join_url, manageUrl });
  }

  return json({ error: 'unknown-action' }, 400);
});
