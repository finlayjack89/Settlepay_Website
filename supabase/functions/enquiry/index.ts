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

// Escape user-supplied text before it goes into an HTML email body.
const esc = (s: string): string =>
  s.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!),
  );

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
      await sendViaResend(resendKey, {
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
      }, 'notification');
    } else {
      console.warn('LEAD_NOTIFY_TO/FROM not set — lead stored but no notification sent.');
    }

    // 3) Auto-acknowledge the enquirer. From a monitored, branded inbox (hello@),
    //    with replies routed there too. Skipped if LEAD_AUTOREPLY_FROM is unset.
    const autoreplyFrom = Deno.env.get('LEAD_AUTOREPLY_FROM');
    if (autoreplyFrom) {
      const firstName = name.split(/\s+/)[0] || name;
      await sendViaResend(resendKey, {
        from: autoreplyFrom,
        to: [email],
        reply_to: notifyTo ?? autoreplyFrom,
        subject: 'Thanks for your enquiry — SettlePay',
        text:
          `Hi ${firstName},\n\n` +
          `Thanks for getting in touch with SettlePay. I've received your enquiry ` +
          `about ${business} and I'll get back to you personally, usually within ` +
          `one working day.\n\n` +
          `If anything's urgent in the meantime, just reply to this email — it ` +
          `comes straight to me.\n\n` +
          `Best regards,\n` +
          `Finlay Salisbury\n` +
          `SettlePay · settlepay.uk`,
        html:
          `<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#0F172A;line-height:1.6;font-size:16px;max-width:560px;">` +
          `<p>Hi ${esc(firstName)},</p>` +
          `<p>Thanks for getting in touch with SettlePay. I've received your enquiry about <strong>${esc(business)}</strong> and I'll get back to you personally, usually within one working day.</p>` +
          `<p>If anything's urgent in the meantime, just reply to this email — it comes straight to me.</p>` +
          `<p style="margin-top:24px;">Best regards,<br>Finlay Salisbury<br>SettlePay</p>` +
          `<p style="color:#64748B;font-size:13px;margin-top:24px;"><a href="https://settlepay.uk" style="color:#64748B;">settlepay.uk</a></p>` +
          `</div>`,
      }, 'autoreply');
    }
  } else {
    console.warn('RESEND_API_KEY not set — lead stored but no email sent.');
  }

  return json({ ok: true, id: data.id });
});
