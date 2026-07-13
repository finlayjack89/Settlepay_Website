// `cal-webhook` — receives Cal.com booking webhooks and upserts public.bookings.
//
// Public endpoint (deploy with --no-verify-jwt): Cal.com signs each request with
// an HMAC-SHA256 of the raw body using the webhook secret, sent in the
// `X-Cal-Signature-256` header. We verify that, not a Supabase JWT.
//
// Provider-agnostic by design: Cal.com supplies the video join link (Cal Video,
// Zoom, Meet…), so nothing here is tied to Microsoft/Teams.
//
// Env (function secrets):
//   CAL_WEBHOOK_SECRET     the same secret set on the Cal.com webhook (required)
//   RESEND_API_KEY         Resend key for the branded confirmation email (optional)
//   BOOKING_CONFIRM_FROM   verified sender, e.g. "SettlePay <hello@settlepay.uk>"
//                          (falls back to LEAD_AUTOREPLY_FROM; unset = no email)
// SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are injected automatically.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { renderBookingConfirmation } from './templates.ts';

const SECRET = Deno.env.get('CAL_WEBHOOK_SECRET') ?? '';
const enc = new TextEncoder();

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

// Constant-time-ish hex compare to verify the Cal.com signature.
async function validSignature(raw: string, header: string): Promise<boolean> {
  if (!SECRET) return false;
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'],
  );
  const mac = await crypto.subtle.sign('HMAC', key, enc.encode(raw));
  const expected = [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, '0')).join('');
  const got = (header || '').trim().toLowerCase();
  if (got.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ got.charCodeAt(i);
  return diff === 0;
}

const firstUrl = (...vals: unknown[]): string | null => {
  for (const v of vals) if (typeof v === 'string' && /^https?:\/\//.test(v)) return v;
  return null;
};

// Extract the video join link. Cal.com puts it in different fields per provider
// (Cal Video → videoCallData/metadata; Google Meet → often only on the resolved
// location / nested references). Try the explicit fields, then fall back to
// scanning the whole payload for a recognised meeting URL, so a Meet link is
// found wherever Cal.com places it.
const VIDEO_URL =
  /https:\/\/(?:meet\.google\.com|[\w.-]*zoom\.us|[\w.-]*\.daily\.co|cal\.(?:com|eu)\/video)\/[^"\\\s]+/;
function extractJoinUrl(p: any): string | null {
  const explicit = firstUrl(p?.metadata?.videoCallUrl, p?.videoCallData?.url, p?.location);
  if (explicit) return explicit;
  const m = JSON.stringify(p ?? {}).match(VIDEO_URL);
  return m ? m[0] : null;
}

// --- Branded confirmation email (best-effort; never fails the webhook) --------
async function sendViaResend(payload: Record<string, unknown>): Promise<void> {
  const key = Deno.env.get('RESEND_API_KEY');
  if (!key) { console.warn('RESEND_API_KEY not set — no booking email sent.'); return; }
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) console.error('booking email send failed:', res.status, await res.text());
  } catch (e) {
    console.error('booking email error:', e);
  }
}

// Format an ISO instant as UK-local date + time for the email body.
function formatWhen(iso: string | null): { date: string; time: string } {
  if (!iso) return { date: '', time: '' };
  const d = new Date(iso);
  const date = new Intl.DateTimeFormat('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'Europe/London',
  }).format(d);
  const time = new Intl.DateTimeFormat('en-GB', {
    hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'Europe/London',
  }).format(d);
  return { date, time };
}

async function sendBookingConfirmation(
  args: { email: string; name?: string | null; startAt: string | null; joinUrl: string | null; uid: string },
): Promise<void> {
  const from = Deno.env.get('BOOKING_CONFIRM_FROM') ?? Deno.env.get('LEAD_AUTOREPLY_FROM');
  if (!from) { console.warn('No booking-email sender set — skipping confirmation.'); return; }
  const { date, time } = formatWhen(args.startAt);
  const firstName = (args.name ?? '').trim().split(/\s+/)[0] || 'there';
  // Fall back to the Cal booking page if no video link is present yet.
  const joinForEmail = args.joinUrl ?? `https://cal.eu/booking/${args.uid}`;
  const { html, text } = renderBookingConfirmation({
    first_name: firstName, date, time, join_url: joinForEmail,
  });
  await sendViaResend({
    from,
    to: [args.email],
    subject: 'Your SettlePay consultation is confirmed',
    html,
    text,
  });
}

Deno.serve(async (req) => {
  if (req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  const raw = await req.text();
  const sig = req.headers.get('x-cal-signature-256') ?? '';
  if (!(await validSignature(raw, sig))) return json({ error: 'bad-signature' }, 401);

  let body: any;
  try {
    body = JSON.parse(raw);
  } catch {
    return json({ error: 'invalid-json' }, 400);
  }

  const event: string = body?.triggerEvent ?? '';
  const p = body?.payload ?? {};
  const uid: string = p?.uid ?? p?.bookingId ?? '';
  if (!uid) return json({ ok: true, ignored: 'no-uid', event }); // e.g. PING / test

  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  if (event === 'BOOKING_CANCELLED') {
    await supabase.from('bookings')
      .update({ status: 'cancelled', raw: body })
      .eq('cal_uid', uid);
    return json({ ok: true, event, uid });
  }

  if (event === 'BOOKING_CREATED' || event === 'BOOKING_RESCHEDULED') {
    const attendee = Array.isArray(p?.attendees) ? p.attendees[0] ?? {} : {};
    const email: string = (attendee?.email ?? '').trim();
    const joinUrl = extractJoinUrl(p);
    const startAt: string | null = p?.startTime ?? null;

    // Existing row? Used for idempotency: only email on a genuinely new or
    // re-timed booking so Cal.com webhook retries don't re-send.
    const { data: existing } = await supabase.from('bookings')
      .select('start_at').eq('cal_uid', uid).maybeSingle();

    // Best-effort link to the originating enquiry (by email). No FK — survives
    // the planned leads -> enquiries rename; ignore errors if the table differs.
    let leadId: string | null = null;
    if (email) {
      const { data: lead } = await supabase.from('leads')
        .select('id').ilike('email', email).order('created_at', { ascending: false })
        .limit(1).maybeSingle();
      leadId = lead?.id ?? null;
    }

    const row = {
      cal_uid: uid,
      status: 'confirmed',
      title: p?.title ?? null,
      start_at: startAt,
      end_at: p?.endTime ?? null,
      attendee_name: attendee?.name ?? null,
      attendee_email: email || null,
      attendee_timezone: attendee?.timeZone ?? null,
      join_url: joinUrl,
      lead_id: leadId,
      raw: body,
    };

    const { error } = await supabase.from('bookings')
      .upsert(row, { onConflict: 'cal_uid' });
    if (error) {
      console.error('booking upsert failed:', error);
      return json({ error: 'store-failed' }, 500);
    }

    // Branded SettlePay confirmation (replaces Cal.com's default email). Only on
    // a new or re-timed booking; never fails the request.
    if (email && (!existing || existing.start_at !== startAt)) {
      await sendBookingConfirmation({ email, name: attendee?.name, startAt, joinUrl, uid });
    }
    return json({ ok: true, event, uid });
  }

  return json({ ok: true, ignored: event }); // unhandled trigger types
});
