# Portfolio demos — the hybrid Stripe test-mode demo

The Marsh & Vale Plumbing & Heating demo
([`src/components/portfolio/demos/MarshValeCheckout.astro`](../src/components/portfolio/demos/MarshValeCheckout.astro))
is a **hybrid**: a pure CSS/JS mock by default, optionally backed by real Stripe **test mode**.
Marsh & Vale is a fictional brand — no real payments are ever taken, in either mode.

## How it works

| Configuration | Behaviour |
|---|---|
| No env vars (default) | The original mock: client-side card formatting/validation, `4242…` succeeds, `4000 0000 0000 0002` declines. No external scripts load. |
| `PUBLIC_STRIPE_TEST_PUBLISHABLE_KEY` only | At build time the mock card fields are replaced by a real **Stripe Payment Element** (deferred-intent mode, £386.40 / GBP), styled to the Marsh & Vale brand via the Appearance API. Stripe.js lazy-loads from `js.stripe.com` on first interaction or near-viewport. On submit, `elements.submit()` validates the details and the success panel shows, labelled *"Validated by Stripe in test mode — confirmation endpoint not configured in this preview"*. |
| Both vars set | After validation the site POSTs `{ amount, currency }` to the Worker, receives `{ clientSecret }`, and confirms the test payment with `stripe.confirmPayment` (3D Secure handled in-page, or via redirect back to the page with `?paid=1`). |

The key is guarded at build time: it must start with `pk_test_`. Anything else — including a
`pk_live_` key — is ignored and the mock renders instead. The site stays fully static: no adapter,
no API routes, no new npm dependencies.

## Getting Stripe test keys

1. Create a free Stripe account at <https://dashboard.stripe.com/register> (no business
   activation needed for test mode).
2. Toggle the dashboard to **Test mode**, then open **Developers → API keys**.
3. Copy the **publishable** test key (`pk_test_…`) into `.env` (copy `.env.example` first).
   The **secret** test key (`sk_test_…`) is only ever used as the Worker secret below.

## Deploying the Worker

The confirmation endpoint is a single-file Cloudflare Worker in
[`serverless/stripe-demo/`](../serverless/stripe-demo/) that creates the test PaymentIntent —
amount and currency are fixed server-side, and it only accepts a `sk_test_` key.

```bash
cd serverless/stripe-demo
npx wrangler login
npx wrangler secret put STRIPE_SECRET_KEY   # paste your sk_test_… key when prompted
npx wrangler deploy
```

Then in the site's `.env`:

```bash
PUBLIC_STRIPE_TEST_PUBLISHABLE_KEY=pk_test_xxxxxxxxxxxx
PUBLIC_STRIPE_DEMO_ENDPOINT=https://settlepay-stripe-demo.<your-subdomain>.workers.dev
```

Rebuild (`npm run build`) — the env vars are baked in at build time. CORS on the Worker allows
only `https://settlepay.uk` and `http://localhost:4321`.

## Test cards

Any future expiry date and any CVC work with all of these:

| Card number | Outcome |
|---|---|
| `4242 4242 4242 4242` | Succeeds |
| `4000 0027 6000 3184` | 3D Secure challenge, then succeeds |
| `4000 0000 0000 0002` | Declined |

## The rule that never bends

**No Stripe secret key (`sk_test_` or `sk_live_`) may ever appear anywhere in this repo** — not in
code, config, docs, comments or commit history. The secret key lives only in the Cloudflare Worker
secret store (`wrangler secret put`). The publishable test key is safe client-side but still
belongs in `.env` (gitignored), never hardcoded. Live keys are refused by both the component and
the Worker.
