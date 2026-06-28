# SettlePay — Email Templates (Export)

Ten email templates + matching plain-text versions + one signature, with
**system colour-mode adaptability built in** (light by default, dark via
`@media (prefers-color-scheme: dark)`). What you previewed is what sends.

## One-time setup: host the two logos

The HTML references the logo at two **absolute URLs** (email images can't use
relative paths). Upload the two PNGs in `assets/` to those exact locations:

- `assets/logo.png`  →  `https://settlepay.uk/email/logo.png`  (light mode — navy glyph)
- `assets/logo-dark.png`  →  `https://settlepay.uk/email/logo-dark.png`  (dark mode — light glyph)

Hosting somewhere else? Do a find-and-replace of `https://settlepay.uk/email/`
across the `.html` files with your own base URL. Nothing else needs changing.

The right logo is shown automatically: light glyph on light, light/white glyph
on dark — one visible at a time, swapped by the dark-mode media query.

## Sending with Resend

For each template, set:

- `html:`  → the contents of `NN-name.html`
- `text:`  → the contents of `NN-name.txt`  (always send both)
- `subject:` → see the list below

Replace every `{{snake_case}}` merge field before sending.

| File | Subject | Merge fields |
|---|---|---|
| 01-enquiry-autoreply | Thanks for your enquiry — SettlePay | first_name, business |
| 02-new-lead-notification | New enquiry — {{business}} | business, name, first_name, email, message, lead_id, submitted_at |
| 03-consultation-confirmation | Your SettlePay Consultation Is Booked | first_name, date, time, reschedule_url |
| 03b-consultation-reminder | Your Consultation Is Coming Up — SettlePay | first_name, date, time, meeting_link, reschedule_url |
| 04-proposal-quote | Your SettlePay Proposal — {{business}} | first_name, business, proposal_url, price_summary, timeline_summary, valid_until |
| 05-follow-up-nudge | Still Thinking It Over? — SettlePay | first_name, business, cta_url, unsubscribe_url |
| 06-onboarding-welcome | Welcome to SettlePay — Let's Get Started | first_name, business, onboarding_url |
| 07-go-live | Your Payment Page Is Live — {{business}} | first_name, business, live_url, summary |
| 08-invoice | Invoice {{invoice_number}} from SettlePay | first_name, invoice_number, amount, issue_date, due_date, pay_url, invoice_url |
| 09-payment-receipt | Payment Received — Thank You | first_name, amount, paid_on, description, receipt_url |
| 10-data-request-ack | We've Received Your Data Request | first_name, request_type |

Only **05-follow-up-nudge** is a marketing/sequence email (it carries the
unsubscribe link). The rest are transactional.

## signature.html

Not an email — paste the block between the `SIGNATURE START / END` comments into
your mail client's signature editor. It uses the same hosted light logo. Fill in
`{{name}}`, `{{role}}`, `{{email}}`, `{{phone}}`.
