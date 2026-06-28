# Enquiry backend — setup & go-live runbook

This wires the site's enquiry form to a Supabase backend (Phase 1): every
submission is stored in a `leads` table you own **and** emailed to you via
Resend. The marketing site stays fully static — it only POSTs to one URL
(`SITE.formEndpoint`). When you later build a CRM dashboard, you build it on top
of this same `leads` table; the website never changes again.

```
Browser form ──POST FormData──▶  enquiry Edge Function  ──┬─▶ insert into public.leads  (source of truth)
                                                          ├─▶ notify the team via Resend (→ hello@)
                                                          └─▶ auto-acknowledge the enquirer via Resend (from hello@)
```

If the endpoint is ever down (e.g. a paused free-tier project), the form falls
back to an honest "open your email app / email us directly" message — no lead is
silently lost.

---

## What you provide (the only manual bits)

- A **Supabase** account + project (free tier is fine to start).
- A **Resend** account + API key, with `settlepay.uk` added as a sending domain.
- A real, monitored inbox for `LEAD_NOTIFY_TO` (e.g. `hello@settlepay.uk`).

Secrets never go in the repo or the site — only into Supabase function secrets.

---

## 1. Create the Supabase project
1. New project → **choose an EU/UK region** (London or Frankfurt). This keeps
   lead data (personal data under UK GDPR) in-region.
2. Note the project ref (the `xxxx` in `https://xxxx.supabase.co`).

## 2. Install + link the CLI
```bash
npm install -g supabase            # or: brew install supabase/tap/supabase
supabase login
supabase link --project-ref <your-project-ref>
```

## 3. Create the leads table (+ RLS + retention)
```bash
supabase db push                   # applies supabase/migrations/*.sql
```
If the `pg_cron` part errors on permissions, enable it once in the dashboard
(**Database → Extensions → pg_cron**), then re-run the cron block from
`supabase/migrations/20260627000000_create_leads.sql` in the SQL editor.

Verify in **Table editor**: a `public.leads` table exists, RLS is on, and
**Database → Cron jobs** lists `purge-stale-leads`.

## 4. Set up Resend
1. Add and verify the **`settlepay.uk`** domain (add the DNS records Resend
   gives you). Until verified you can test with the `onboarding@resend.dev`
   sender, but production should send from your domain.
2. Create an **API key**.

## 5. Set the function secrets
```bash
cp supabase/functions/enquiry/.env.example supabase/functions/enquiry/.env
# edit .env: RESEND_API_KEY, LEAD_NOTIFY_TO, LEAD_NOTIFY_FROM,
#            LEAD_AUTOREPLY_FROM (optional — the customer acknowledgement), ALLOWED_ORIGIN
supabase secrets set --env-file supabase/functions/enquiry/.env
```
`LEAD_AUTOREPLY_FROM` should be a **monitored, replyable** address (e.g.
`SettlePay <hello@settlepay.uk>`) — the enquirer gets a branded "we've received
your enquiry" email from it, and their replies route back to `LEAD_NOTIFY_TO`.
Leave it blank to disable the autoreply.
(`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` are injected automatically — don't set them.)

## 6. Deploy the function (public — no JWT)
```bash
supabase functions deploy enquiry --no-verify-jwt
```
`--no-verify-jwt` is **required**: the anonymous form POST has no Supabase auth
header, so without it every submission would 401.

Your endpoint is:
```
https://<your-project-ref>.supabase.co/functions/v1/enquiry
```

## 7. Point the site at it
In [`src/data/site.mjs`](../src/data/site.mjs) set:
```js
formEndpoint: 'https://<your-project-ref>.supabase.co/functions/v1/enquiry',
```
Then rebuild/redeploy the site (`npm run build`). The form auto-switches from
the mailto fallback to real POST submission — no other code change.

## 8. Test end to end
- Submit the form on the live site (use a real address you control as the enquirer).
- Confirm a row appears in **Table editor → leads**.
- Confirm the notification email arrives at `LEAD_NOTIFY_TO`.
- Confirm the **autoreply** arrives at the address you submitted, and that
  replying to it lands at `LEAD_NOTIFY_TO`.
- Submit with a fake/invalid email → expect the form's error state, no row.

---

## Compliance follow-through (do before go-live)
These are promises the [Privacy Policy](../src/pages/privacy.md) already makes —
storing leads makes them real obligations:

- [ ] **Accept the DPAs** for Supabase and Resend (both offer standard ones).
- [ ] **Confirm the EU/UK region** (step 1) and that both providers' SCCs cover
      any transfer (the policy's "International Transfers" section).
- [ ] **Retention job live** — verify `purge-stale-leads` exists (step 3). It
      deletes non-client leads ~12 months after last contact, per the policy.
- [ ] **ICO registration** — storing personal data electronically as a business
      makes this clearly required. Finish it and fill `SITE.icoRegistration`.
- [ ] Be able to honour access/erasure requests — find a lead by email in the
      Table editor and export/delete it on request.

---

## Phase 2 — the CRM (later, no website changes)
The data is already accumulating in `leads`. To build the dashboard:
- Add **Supabase Auth** and RLS policies on `leads` for your authenticated user.
- Build a small admin app (Astro+React / Next) reading/writing the same table —
  the `status` column (`new → contacted → quoted → won/lost/client`) and `notes`
  are already there for a pipeline.
- Optionally push leads to a third-party CRM (e.g. HubSpot) from the Edge
  Function while keeping the owned copy here.
