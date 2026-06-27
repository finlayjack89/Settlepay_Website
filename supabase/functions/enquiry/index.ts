// `enquiry` Edge Function — the conversion endpoint for the SettlePay site.
//
// Receives the EnquireModal form POST (multipart FormData), stores the lead in
// public.leads (source of truth), and emails a notification via Resend.
// Public endpoint: deploy with `--no-verify-jwt` so the anonymous form POST
// (which carries no Supabase auth header) is accepted.
//
// Env (set as function secrets — see supabase/functions/enquiry/.env.example):
//   RESEND_API_KEY     Resend API key (notification email)
//   LEAD_NOTIFY_TO     where lead emails are sent (e.g. hello@settlepay.uk)
//   LEAD_NOTIFY_FROM   verified Resend sender (e.g. "SettlePay <notifications@settlepay.uk>")
//   ALLOWED_ORIGIN     CORS origin to allow (default "*"; set to https://settlepay.uk in prod)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2';

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

  // 2) Notify by email. The lead is already saved, so an email failure must
  //    NOT fail the request — log it and still return success.
  const resendKey = Deno.env.get('RESEND_API_KEY');
  const notifyTo = Deno.env.get('LEAD_NOTIFY_TO');
  const notifyFrom = Deno.env.get('LEAD_NOTIFY_FROM');

  if (resendKey && notifyTo && notifyFrom) {
    try {
      const res = await fetch('https://api.resend.com/emails', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${resendKey}`,
          'content-type': 'application/json',
        },
        body: JSON.stringify({
          from: notifyFrom,
          to: [notifyTo],
          reply_to: email,
          subject: `New enquiry — ${business}`,
          text:
            `New consultation enquiry via settlepay.uk\n\n` +
            `Business: ${business}\n` +
            `Name: ${name}\n` +
            `Email: ${email}\n\n` +
            `Message:\n${message}\n\n` +
            `— Lead ID: ${data.id}`,
        }),
      });
      if (!res.ok) {
        console.error('resend send failed:', res.status, await res.text());
      }
    } catch (e) {
      console.error('resend error:', e);
    }
  } else {
    console.warn('Resend env not fully set — lead stored but no email sent.');
  }

  return json({ ok: true, id: data.id });
});
