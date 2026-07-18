# Pre-live-send blockers — scope & what's built

The two things that must exist before `G_SEND` is ever set. Both have their
**mechanism built and tested now**; both have a **provisioning step that is yours**
(credentials / DNS) because I can't and shouldn't create those. Live sending stays
hard-gated until you complete the provisioning and clear the gates.

---

## Blocker A — Reply / bounce / unsubscribe ingestion

**Why it blocks go-live:** without it we would re-email people who asked to stop (a
PECR breach), keep hard-bouncing into a fresh domain (destroying its reputation),
and have no bounce rate — which the graduation policy requires.

### ✅ Built (`outreach/inbound.py`, migration 0004) — testable now
- A swappable `MailboxSource` (project pattern): `InlineMailboxSource` (tests / dry-run)
  today; the live **Gmail** read is a tracked follow-up (the mailboxes moved to Google
  Workspace, retiring the old Graph reader — reading needs a broader `gmail.readonly`
  scope than the send-only token).
- `classify(msg)` → `bounce | unsubscribe | complaint | reply` (fail-safe: anything
  that reads like a stop request is treated as one).
- `ingest()` is **idempotent** (dedupes on provider message id) and writes the loop:
  - bounce → `suppressions` + lead `bounced`
  - unsubscribe / complaint → `suppressions` + lead `suppressed`
  - reply → lead `replied`
  - every action gets an `audit_log` row.
- `check_suppression` (already enforced before every send) consumes these, so a
  suppressed/bounced/opted-out contact can never be re-emailed.
- Surfaced on the dashboard (Compliance panel) + Settings (Inbound panel).
- CLI: `python -m outreach.inbound`

### 🔧 You provision
1. A **dedicated sending domain + mailbox** on **Google Workspace** (a secondary
   domain, e.g. `finlay@getsettlepay.uk`) — **never `@settlepay.uk`**.
2. A **Google Cloud OAuth client** ("Internal" in our Workspace — no verification).
   For sending, consent once with the `gmail.send` scope via
   `python -m outreach auth-google`. (Reading replies later needs a broader
   `gmail.readonly`/`modify` scope + its own consent — the inbound follow-up.)
3. Put the values in `outreach/.env`: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `GOOGLE_REFRESH_TOKEN`, `GMAIL_SENDER`. Inbound ingestion stays `INBOUND_SOURCE=inline`
   (feed messages manually) until the Gmail reader lands.

### Then operate it
Run `python -m outreach.inbound` on a schedule (cron / a `/schedule` routine) so
opt-outs and bounces are honoured continuously — ideally **before** each send batch.

---

## Blocker B — Domain warm-up + SPF / DKIM / DMARC

**Why it blocks go-live:** a cold mailbox on a domain without authentication, sent at
full volume from day one, lands in spam — wasting the entire funnel at the last step.

### ✅ Built — testable now
- **Warm-up ramp** (`sequence_config.json` `warmup`, `sequence.warmup_cap`): a
  per-inbox daily ceiling that ramps a new mailbox up gradually
  (`5 → 50/day`) and holds at steady. `send.py` enforces it: effective cap =
  `min(PER_INBOX_DAILY_CAP, warmup_cap(day))`, where the warm-up day is derived from
  the inbox's first **live** send. Shown in Settings → Deliverability.
- **Auth readiness check** (`outreach/dns_auth.py`): verifies SPF + DKIM + DMARC
  exist for the sending domain via DNS-over-HTTPS (no new dependency).
  CLI: `python -m outreach.dns_auth [domain] [dkim_selector]`.

### 🔧 You provision (DNS for the sending domain)
- **SPF**  `TXT @  "v=spf1 include:_spf.google.com ~all"`
- **DKIM**  generate in Google Workspace Admin (Apps → Gmail → Authenticate email) and
  publish the `google._domainkey` TXT it gives you.
- **DMARC**  `TXT _dmarc  "v=DMARC1; p=quarantine; rua=mailto:dmarc@<domain>"`
  (start at `p=none` to monitor, move to `quarantine`/`reject`).
- Then confirm with `python -m outreach.dns_auth` (all three → READY yes).
- **Warm up** for ~2–4 weeks (the ramp handles volume; keep early sends low and
  high-quality) before raising `PER_INBOX_DAILY_CAP` to the steady ceiling.

---

## Go-live checklist (all must be true before setting `G_SEND`)

- [ ] Dedicated Google Workspace sending domain + mailbox provisioned (not `@settlepay.uk`)
- [ ] Google OAuth: `gmail.send` consented via `python -m outreach auth-google`; creds in `.env`
- [ ] `python -m outreach.dns_auth` → SPF + DKIM + DMARC all **READY**
- [ ] `python -m outreach.inbound` scheduled (opt-outs/bounces honoured continuously)
- [ ] Warm-up underway; `PER_INBOX_DAILY_CAP` still conservative
- [ ] Legitimate-interests assessment (LIA) documented for the sending domain
- [ ] Drafting **playbook v1** approved (real copy + cadence) — separate workstream
- [ ] A human sets `G_SEND` (the loop never can). Risky/catch-all tier also needs
      `RISKY_SEND_ENABLED`.

Everything above the last line is mechanism + policy that exists today; the last line
is the deliberate human act that turns it on.
