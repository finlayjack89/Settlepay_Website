# Booking + CRM — Architecture Decision Doc

**Status:** planning (no code written). **Decision needed:** Path A vs Path B.
**First milestone (agreed):** booking → calendar → Teams link working end-to-end.

## Goal
A prospect books a consultation from the site → it lands on Finlay's calendar →
a Teams meeting link is generated → they get a branded confirmation now and a
reminder with the join link before the call → later, all of this is visible in a
CRM alongside leads.

## What already exists
- **Microsoft 365** mailbox `finlay@settlepay.uk` (GoDaddy-provisioned tenant).
- **Supabase** (EU project, `leads` table, Edge Functions, `pg_cron`, RLS).
- **Resend** (verified domain, branded email templates 01–10 + 03b).
- **Astro** static site on Vercel; **Bookings/CRM are not built**.

---

## ⚠️ Step 0 (blocks BOTH paths) — licensing
Teams meeting links require a **Teams licence**, and Microsoft Bookings requires a
**Bookings-enabled plan**. GoDaddy's *email-only* M365 tiers (Exchange Online) include
**neither**. Check `finlay@settlepay.uk`'s plan:
- **Business Basic / Standard / Premium** → Teams **and** Bookings included. ✅ either path works.
- **Email-only (Email Essentials/Plus)** → no Teams, no Bookings. ❌ must upgrade
  (~£5–10/user/mo, verify current pricing) before *any* Teams-based flow — Path A or B.

Everything below assumes a Teams-capable plan.

---

## Path A — Microsoft Bookings + custom CRM  (recommended)

Use Microsoft's native scheduling product for the booking loop; build only the CRM.

### Booking + Teams milestone (mostly configuration, not code)
1. Create a **Bookings** calendar "SettlePay Consultations".
2. Add a **Service** "Free Consultation" (e.g. 30 min) with **online meeting = ON**
   → every booking auto-creates a **Teams link**; set buffers, lead time, business hours.
3. **Staff = Finlay**, linked to his Outlook calendar → availability pulled from
   free/busy; bookings write to his calendar (he sees his schedule in Outlook).
4. **Publish** the self-service booking page; point the site's "Book a Consultation"
   CTA at it.
5. Bookings then handles confirmations, reminders, reschedule/cancel, and the
   customer's calendar invite — automatically.

**Effort:** ~½–1 day (admin config + light styling). **No Graph, no code** for the
core loop.

### Branded emails (two sub-options)
- **A1 (fast):** use Bookings' built-in emails. Editable text + logo, but *not* our
  full HTML 03/03b — looks plainer.
- **A2 (branded):** disable Bookings' emails; our system sends 03/03b via Resend,
  triggered by **Microsoft Graph change notifications** (webhook) on the booking
  calendar → a Supabase Edge Function stores the booking + schedules the reminder
  (`pg_cron`) → branded send. Adds the Entra app + a webhook receiver (~2–4 days).

### CRM (separate phase, the real build)
- **Supabase Auth** (Finlay logs in) + a dashboard (small SSR app or React island —
  separate from the static marketing site).
- Reads **leads** (existing table) + **schedule** (Bookings appointments / calendar
  via Graph `solutions/bookingBusinesses` or `/events`, read-only).
- Pipeline view (`new → contacted → quoted → won/lost`) + upcoming consults.

### Pros / Cons
+ Minimal build for scheduling; Microsoft maintains availability, timezones,
  reschedule, reminders, Teams, calendar. Robust from day one.
+ Build effort goes to the CRM — the actual differentiator.
− Bookings emails are minimally branded unless you do A2.
− Bookings page styling is limited (Microsoft look); less control of booking UX.

---

## Path B — fully custom

Build the whole loop on Supabase + Microsoft Graph + Astro.

### Booking + Teams milestone (code)
1. **Entra (Azure AD) app registration** + Graph **application** permissions
   (`Calendars.ReadWrite`), admin consent, and an **Exchange Application Access
   Policy** scoping the app to `finlay@` only (security).
2. **Booking page** (Astro + a React island): render available slots. Availability
   from Graph `getSchedule` (real free/busy) or a simpler business-hours + DB check.
3. **Edge Function on submit:**
   - re-check the slot is free;
   - `POST /users/{finlay}/events` with `isOnlineMeeting:true,
     onlineMeetingProvider:"teamsForBusiness"` → books the calendar **and** returns
     the Teams `joinUrl` in one call;
   - store in a Supabase `bookings` table (joinUrl, time, client, status);
   - send confirmation (03) via Resend.
4. **Reminder:** `pg_cron` scans for bookings within N hours, `reminder_sent=false`
   → send 03b with the joinUrl.
5. **Reschedule/cancel:** token-based links in emails → a manage page → update the
   Graph event + Supabase.

### CRM
- Same as Path A, but bookings already live in Supabase (no Graph read needed for
  schedule — it's in your DB).

### Pros / Cons
+ Full control of booking UX; fully branded emails throughout; bookings native in
  your CRM DB; no Bookings-product limitations.
− Much more to build and maintain: availability + timezone + reschedule + no-show
  logic, reminder cron, error handling.
− Graph application-permission + Teams setup is fiddly (app access policy).
− You re-implement what Bookings already does well. ~1–3 weeks to a robust v1.

---

## Side-by-side

| | Path A (Bookings + CRM) | Path B (fully custom) |
|---|---|---|
| Booking+Teams effort | ~½–1 day (config) | ~1–2 weeks |
| Branded consult emails | A2 add-on (~2–4 days) | built-in |
| Availability/timezone/reschedule | Microsoft handles | you build |
| Booking-page branding | limited | full |
| Maintenance | low | ongoing |
| Extra licence | Bookings plan | Teams plan (for links) |
| Graph app registration | only for A2 / CRM read | required |

## Recommendation
**Path A (with A2 when you want branded consult emails).** For a sole trader, get
scheduling/Teams/calendar from Bookings (configuration, not code) and spend the
build budget on the **CRM**, which is the part that doesn't exist and actually
differentiates you. Choose Path B only if the Bookings booking-page UX/branding is
a genuine dealbreaker.

## Open items before build
1. Confirm the M365 licence (Step 0).
2. Pick Path A or B.
3. (A2 / Path B / CRM) Create the Entra app registration — I'll give exact steps.
