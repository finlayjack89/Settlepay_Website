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
//   CAL_WEBHOOK_SECRET   the same secret set on the Cal.com webhook (required)
// SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are injected automatically.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

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
    const joinUrl = firstUrl(p?.metadata?.videoCallUrl, p?.videoCallData?.url, p?.location);

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
      start_at: p?.startTime ?? null,
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
    return json({ ok: true, event, uid });
  }

  return json({ ok: true, ignored: event }); // unhandled trigger types
});
