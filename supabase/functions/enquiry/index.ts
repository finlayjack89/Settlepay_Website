// `enquiry` Edge Function — the conversion endpoint for the SettlePay site.
//
// Receives the EnquireModal form POST (multipart FormData), stores the lead in
// public.leads (source of truth), notifies the team and auto-acknowledges the
// enquirer via Resend.
// Public endpoint: deploy with `--no-verify-jwt` so the anonymous form POST
// (which carries no Supabase auth header) is accepted.
//
// Env (set as function secrets — see supabase/functions/enquiry/.env.example):
//   RESEND_API_KEY     Resend API key (notification + autoreply email)
//   LEAD_NOTIFY_TO     where lead emails are sent (e.g. hello@settlepay.uk)
//   LEAD_NOTIFY_FROM   verified Resend sender (e.g. "SettlePay <notifications@settlepay.uk>")
//   LEAD_AUTOREPLY_FROM  optional — branded sender for the customer acknowledgement
//                        (e.g. "SettlePay <hello@settlepay.uk>"); unset = no autoreply
//   ALLOWED_ORIGIN     CORS origin to allow (default "*"; set to https://settlepay.uk in prod)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';
import { renderAutoreply, renderNotification } from './templates.ts';

const ALLOWED_ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? '*';

const cors = {
  'Access-Control-Allow-Origin': ALLOWED_ORIGIN,
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type, accept',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, 'content-type': 'application/json' },
  });
}

const str = (v: FormDataEntryValue | null): string =>
  typeof v === 'string' ? v.trim() : '';

// Send one email via Resend. Lead is already saved by the time we call this, so
// a send failure must never throw — log it and move on.
async function sendViaResend(
  key: string,
  payload: Record<string, unknown>,
  label: string,
): Promise<void> {
  try {
    const res = await fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: `Bearer ${key}`, 'content-type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) console.error(`${label} send failed:`, res.status, await res.text());
  } catch (e) {
    console.error(`${label} error:`, e);
  }
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return json({ error: 'method-not-allowed' }, 405);

  let form: FormData;
  try {
    form = await req.formData();
  } catch {
    return json({ error: 'invalid-form' }, 400);
  }

  // Honeypot: bots fill _gotcha. Pretend success and store nothing.
  if (str(form.get('_gotcha'))) return json({ ok: true });

  const business = str(form.get('business'));
  const name = str(form.get('name'));
  const email = str(form.get('email'));
  const message = str(form.get('message'));

  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  if (!business || !name || !message || !emailOk) {
    return json({ error: 'validation', detail: 'Missing or invalid fields.' }, 400);
  }

  const firstName = name.split(/\s+/)[0] || name;

  // 1) Store the lead. Service-role key bypasses RLS. This is the source of
  //    truth, so a failure here is the only thing that fails the request.
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
  );

  const { data, error } = await supabase
    .from('leads')
    .insert({ business, name, email, message })
    .select('id')
    .single();

  if (error) {
    console.error('lead insert failed:', error);
    return json({ error: 'store-failed' }, 500); // client shows "email us directly"
  }

  // The lead is saved, so the rest is best-effort: an email failure must NOT
  // fail the request — each send logs and returns success regardless.
  const resendKey = Deno.env.get('RESEND_API_KEY');

  if (resendKey) {
    // 2) Notify the team. From notifications@, reply-to the enquirer so a reply
    //    in your inbox goes straight back to them.
    const notifyTo = Deno.env.get('LEAD_NOTIFY_TO');
    const notifyFrom = Deno.env.get('LEAD_NOTIFY_FROM');
    if (notifyTo && notifyFrom) {
      const notif = renderNotification({
        business, name, first_name: firstName, email, message,
        lead_id: data.id,
        submitted_at: new Date().toLocaleString('en-GB', {
          timeZone: 'Europe/London', dateStyle: 'medium', timeStyle: 'short',
        }),
      });
      await sendViaResend(resendKey, {
        from: notifyFrom,
        to: [notifyTo],
        reply_to: email,
        subject: `New enquiry — ${business}`,
        html: notif.html,
        text: notif.text,
      }, 'notification');
    } else {
      console.warn('LEAD_NOTIFY_TO/FROM not set — lead stored but no notification sent.');
    }

    // 3) Auto-acknowledge the enquirer. From a monitored, branded inbox (hello@),
    //    with replies routed there too. Skipped if LEAD_AUTOREPLY_FROM is unset.
    const autoreplyFrom = Deno.env.get('LEAD_AUTOREPLY_FROM');
    if (autoreplyFrom) {
      const auto = renderAutoreply({ first_name: firstName, business });
      await sendViaResend(resendKey, {
        from: autoreplyFrom,
        to: [email],
        reply_to: notifyTo ?? autoreplyFrom,
        subject: 'Thanks for your enquiry — SettlePay',
        html: auto.html,
        text: auto.text,
      }, 'autoreply');
    }
  } else {
    console.warn('RESEND_API_KEY not set — lead stored but no email sent.');
  }

  return json({ ok: true, id: data.id });
});
