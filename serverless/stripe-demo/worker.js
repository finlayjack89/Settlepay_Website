/**
 * SettlePay portfolio demo — Stripe TEST-mode PaymentIntent Worker.
 *
 * Creates a fixed £386.40 test PaymentIntent for the Marsh & Vale demo
 * (a fictional brand — no real payments are ever taken). Plain fetch to the
 * Stripe REST API; no SDK, no dependencies.
 *
 * Deploy (from this directory):
 *   1. npx wrangler login
 *   2. npx wrangler secret put STRIPE_SECRET_KEY     # paste your sk_test_… key only
 *   3. npx wrangler deploy
 *   4. Set PUBLIC_STRIPE_DEMO_ENDPOINT in the site's .env to the Worker URL.
 *
 * The secret key lives ONLY in the Worker secret store — never in this repo,
 * never in the site, never in wrangler.toml. The Worker refuses to run with
 * anything other than a TEST secret key (sk_test_…).
 */

const ALLOWED_ORIGINS = ['https://settlepay.uk', 'http://localhost:4321'];

// Fixed server-side — any amount/currency sent by the client is ignored.
const AMOUNT = 38640; // £386.40 in pence
const CURRENCY = 'gbp';

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function json(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(origin) },
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get('Origin') || '';
    if (!ALLOWED_ORIGINS.includes(origin)) {
      return new Response('Forbidden', { status: 403 });
    }
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }
    if (request.method !== 'POST') {
      return new Response('Method Not Allowed', {
        status: 405,
        headers: { Allow: 'POST, OPTIONS', ...corsHeaders(origin) },
      });
    }

    const key = env.STRIPE_SECRET_KEY || '';
    if (!key.startsWith('sk_test_')) {
      // Live keys are refused outright — this Worker is test mode only.
      return json({ error: 'Worker is not configured with a Stripe TEST secret key.' }, 500, origin);
    }

    const params = new URLSearchParams({
      amount: String(AMOUNT),
      currency: CURRENCY,
      'automatic_payment_methods[enabled]': 'true',
      description:
        'SettlePay portfolio demo — Marsh & Vale (fictional brand), invoice INV-2147. Test mode only.',
    });

    let stripeResponse;
    try {
      stripeResponse = await fetch('https://api.stripe.com/v1/payment_intents', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${key}`,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: params,
      });
    } catch {
      return json({ error: 'Could not reach Stripe.' }, 502, origin);
    }

    const data = await stripeResponse.json();
    if (!stripeResponse.ok || !data.client_secret) {
      return json({ error: 'Could not create the test payment.' }, 502, origin);
    }

    return json({ clientSecret: data.client_secret }, 200, origin);
  },
};
