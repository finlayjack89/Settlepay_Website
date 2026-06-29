# outreach-build — durable context (read-only each run)

This is the bridge that carries design-time decisions into the cold-started loop.
The running loop does **not** have the chat this came from — everything it must
respect is pinned here. Read this top-to-bottom at the start of every run, then
read `STATE.md` for where you are.

---

## What this loop builds (and what it must NEVER do)

A UK **PECR-compliant agentic cold-email outreach pipeline** for SettlePay, in
its own project at **`outreach/`** (Python 3.12, top-level folder in this repo,
fully separate from the Astro website code). The pipeline writes to the **same
Supabase Postgres** that backs the website's enquiry form.

The loop builds the pipeline **phase by phase** (manifest A→H), one phase per
iteration: **implement → floor → judge → record → advance**. A phase is GREEN
only when `verify.sh` (deterministic floor) exits 0 **AND** a separate judge
agent returns PASS.

> **The loop builds the drafting MECHANISM only.** It never invents conversion
> copy, personalisation depth, follow-up timing, send windows, or sequence
> cadence. See "DEFERRED — out of remit" below. This is the single most important
> rule after the compliance firewall.

---

## Harvested decisions (from the design discussion — non-obvious, honour these)

1. **`outreach/` is a top-level folder in THIS repo** (not a separate repo). One
   worktree (`../worktrees/outreach-build`, branch `feat/outreach-build` off
   origin/main), one PR — same model as the `demo-fit` loop. The pipeline keeps a
   local `outreach/.gitignore` (ignores `.env`, `.venv/`, `__pycache__/`); also
   add `outreach/` to a root **`.vercelignore`** so Vercel never builds the Python
   project.
2. **Data model — separate `outreach` schema (CONFIRMED by inspecting the live
   DB).** The earlier assumption that `enquiries` exists was WRONG: the live
   `public` schema has only **`leads`** (the website's INBOUND enquiry capture:
   columns business/name/email/message/source/status/notes). No `enquiries` table
   exists yet (the Edge Function repoint `leads → enquiries` is the user's
   uncommitted WIP). To avoid colliding with website-owned data, the pipeline
   lives in its **own `outreach` schema** (`outreach.leads` = OUTBOUND cold leads,
   `outreach.drafts`, etc.). It **never** creates/alters/writes any `public`
   table. The firewall suppresses against the website's inbound source —
   **`public.<ENQUIRY_SOURCE_TABLE>`**, env-configurable: **`leads` now**, switch
   to **`enquiries`** once the user deploys the repoint. Touching the website repo
   / Edge Function is still **OUT of remit → halt to G2**.
   - Connection: the direct host `db.<ref>.supabase.co` is **IPv6-only and does
     not resolve** on IPv4 networks. Use the **session pooler**
     (`postgresql://postgres.<ref>:<pw>@aws-1-eu-north-1.pooler.supabase.com:5432/postgres`).
     `db.py` pins `search_path` to `outreach, public`.
3. **Live sending is the most heavily gated item** and never passes on the loop's
   own authority. Until **G-SEND** is cleared by a human, the send path is
   **dry-run / test-mailbox only**, and the loop must never set `G_SEND`.
4. **Budget:** max 2 fix-rounds per phase; max 90 min wall-clock per run; CH
   ≤50 req/run during build (≤600/5min ceiling honoured in code);
   MillionVerifier ≤20 verifications/run; LLM via the **inline** provider (no
   API spend by default). All counters live in `STATE.md`.

---

## Stack (durable)

- **Python 3.12**; `httpx` for HTTP.
- **psycopg (v3) or SQLAlchemy** over **Supabase Postgres** — NOT SQLite (Postgres
  already exists in Supabase). Connect as **SERVICE ROLE**, server-side only,
  **never** the browser. Supabase project ref: **`xqpbcoldcqfxfwhcqlcy`**.
- **LLMProvider** — a swappable interface with two implementations, built now,
  both callable, **default `inline`**:
  - **`inline`** (default): when the loop runs via `/loop` on the Claude Max
    subscription, the **loop agent itself** performs the enrichment-summary and
    draft-writing reasoning — no API key, draws on Max. The provider hands the
    agent a structured prompt and **records its output** into the DB.
  - **`api`**: a later Anthropic API implementation for the unattended
    cron/dashboard runtime. Build the interface and a working stub now; do not
    spend API tokens during build.
- **Lead source:** Companies House **Advanced Search API** (free; env
  `COMPANIES_HOUSE_API_KEY`).
- **Email verify:** **MillionVerifier** (env; small samples only during build).
- **Send (phase G):** **Microsoft Graph API** from a **SEPARATE warmed domain
  mailbox** (`settlepayhq.uk` or similar — **TBD**), **never `@settlepay.uk`**.
  Dry-run only until **G-SEND** clears.
- **Secrets in `outreach/.env` only, never committed.**

---

## DEFERRED — OUT OF REMIT (do not let the loop wander into this)

The drafting **CONVERSION STRATEGY** — email copy, personalisation depth,
follow-up timing, send windows, sequence cadence — is **NOT** invented by this
loop. It arrives separately as a researched **"drafting playbook"**:
an editable `outreach/prompts/draft_email.md` + a `sequence_config`. The loop
builds the **mechanism** that loads and enforces these, with **placeholder
content**, and must never substitute its own conversion tactics.

If a phase appears to need conversion-strategy decisions (what to say, when to
send, how many follow-ups, what cadence), that is **deferred work → halt to G2**.
Use the placeholder and move on. **Do not guess copy or timing.**

### The verbatim placeholder the loop must write to `outreach/prompts/draft_email.md`

Phase E must create this file with **exactly** this content (do not "improve" it —
inventing real copy here is the failure mode the floor and judge guard against):

```markdown
<!-- PLACEHOLDER — drafting playbook v0. DO NOT TREAT AS REAL COPY. -->
<!-- The conversion strategy (copy, tone, personalisation, follow-up timing,    -->
<!-- send windows, sequence cadence) is DEFERRED and arrives as a separately    -->
<!-- researched drafting playbook. This file only proves the MECHANISM loads a  -->
<!-- prompt and enforces the structural/compliance envelope. Replace this whole -->
<!-- file with the researched playbook v1 before any live send (gate G-SEND).   -->

# SettlePay cold-email draft prompt — PLACEHOLDER v0

ROLE: Write a short plain-text outreach email from SettlePay to a UK estate
agency, on behalf of Finlay Salisbury (sole trader, trading as SettlePay).

HARD ENVELOPE (the mechanism enforces these — the floor will reject violations):
- Plain UK English, under 125 words.
- Plain-text only: ZERO links, ZERO images, ZERO tracking.
- Include a plain-text unsubscribe line.
- Include a clear SettlePay sender identification.
- If payments/authorisation are mentioned, say payments are processed by
  "FCA-regulated partners" — NEVER claim SettlePay is itself FCA authorised,
  PCI compliant, or a limited company.

CONTENT: <DEFERRED — the researched playbook supplies the actual value
proposition, personalisation, and call to action. Until then, produce a minimal,
compliant, clearly-provisional message that satisfies the envelope above and
references the recipient's company name and the enrichment signal only.>
```

---

## Phases (detail) — each GREEN predicate is the floor's contract

The machine-readable predicates live in `manifest.json`; build to those. Notes
that aren't obvious from the manifest:

- **A — Foundations.** `drafts` MUST store BOTH `body_original` (the AI draft,
  **immutable** once written) AND `body_final` (after any human edit). The diff
  between them is the **primary training signal for playbook v2** — this is why
  both columns are mandatory, not a nicety. State machine + audit_log writer with
  unit tests.
- **B — find_leads.** SIC `68310` (estate agents), `company_status=active`,
  paged via `start_index`, dedupe on `company_number`, write `state=discovered`.
  Stay under 600 req / 5 min (build cap ≤50 req/run).
- **C — Compliance firewall (PECR).** See the dedicated section below.
- **D — enrich_company.** Prefer **generic** mailboxes (`info@`, `contact@`) over
  named individuals (a personal-name mailbox tilts toward "individual subscriber"
  — a PECR risk). Discard unverifiable emails; an unverifiable email must never
  remain on a contactable lead.
- **E — draft_email (MECHANISM ONLY).** Load the placeholder, draft into
  `body_original` via the inline provider, enforce the structural/compliance
  envelope. GREEN is **purely structural/compliance** — conversion quality
  genuinely cannot be verified at build time.
- **F — Approval queue.** Edit → `body_final` + `reviewer_note` (leave
  `body_original` intact); approve-without-edit copies `body_original` →
  `body_final`. Only approved drafts advance; nothing advances without a recorded
  human decision.
- **G — send.** Hard-gated, OFF by default. See INVARIANTS + G-SEND.
- **H — Operational wiring.** `python -m outreach run --stage all` advances each
  lead one step per tick. Timing is **config-driven** via `sequence_config`
  (values TBD from the playbook — **no hardcoded delays**). Graduation thresholds
  encoded; kill switch wired.

---

## Compliance firewall (phase C) — the PECR core, get this exactly right

UK PECR distinguishes **corporate subscribers** (companies, LLPs — cold B2B email
permissible under legitimate interests with an opt-out) from **individual
subscribers** (sole traders, individuals — cold email generally **not**
permitted). Therefore:

- Classify each lead's legal structure into **`corporate` / `individual` /
  `unknown`** from Companies House `company_type` (and `company_status`).
- **`individual` OR `unknown` → hard-move to `state=suppressed`**, reason
  `"PECR individual subscriber"`, **never contactable**. Unknown is treated as
  individual — fail safe, never fail open.
- `check_suppression(email, domain, company_number)` consults **BOTH**
  `outreach.suppressions` AND the website's inbound source
  **`public.<ENQUIRY_SOURCE_TABLE>`** (`leads` now → `enquiries` after the
  repoint) — **never cold-contact an existing enquirer** (someone who already
  filled in the website form).
- Every lead gets an `audit_log` row recording **source** +
  `lawful_basis="legitimate interests"` + the **classification reason**.

> SettlePay itself is a **sole trader** (trading name of Finlay Salisbury). That
> is the SENDER's status and is fine. The firewall classifies the **RECIPIENT**.
> Do not conflate the two.

If the classifier is genuinely ambiguous on a real `company_type` value, that is
**G2 anomaly territory** — suppress (fail safe) and surface it; do not invent a
rule.

---

## INVARIANTS (hold every run — the floor and judge enforce these)

- **No live cold-email send, ever, without human gate G-SEND cleared.** The loop
  cannot set it.
- The loop builds the drafting **mechanism only**; it **never** invents conversion
  copy or timing.
- **Individual/unknown subscribers are NEVER in a contactable state.**
- `check_suppression` (suppressions ∪ enquiries) runs **before ANY send**.
- **`body_original` is immutable** once written; human edits go to `body_final`.
- Per-inbox daily cap and the kill switch are **always** respected.
- **Never on `main`; never auto-merge** — a PR is the human gate (G3).
- **Secrets only in `outreach/.env`, never committed.**
- **UK English, £, real SettlePay identity.** Never claim SettlePay's own FCA
  authorisation / PCI compliance; never write "Ltd" or a company number (sole
  trader). Payments are processed by **FCA-regulated partners**.

---

## Verifier = floor + judge (independent of the loop's reasoning)

- **FLOOR (binary, deterministic):** `loops/outreach-build/verify.sh` — asserts
  the current phase's GREEN predicate via pytest + read-only SQL
  (`floor_db.py`) + file/grep checks. Exit 0 = PASS; non-zero = FAIL naming the
  failing checks. The floor's logic lives in `verify.sh` (loop-maker-owned), NOT
  in code the build loop writes — so it can't be gamed.
- **JUDGE (a SEPARATE agent, never the builder):** spawn a distinct evaluator
  agent and give it the phase's diff/output + the rubric below. It returns
  **PASS / NEEDS-WORK + notes**, which the loop records in `STATE.md`. The judge
  **never edits code**.

### Judge rubric (what the separate evaluator checks)

- **PECR correctness**, especially the firewall: individual/unknown never
  contactable; unknown failed safe; enquirers suppressed; lawful_basis logged.
- **No secrets in code** — keys only in `.env`, never committed.
- The drafting **mechanism is clean** and the **placeholder is clearly marked** —
  and crucially, **no conversion strategy was invented by the loop** (NOT whether
  the copy converts — that's deferred and unjudgeable here).
- The **LLMProvider abstraction is intact** (inline default; api stubbed; both
  callable; swappable).
- **`body_original` / `body_final` handling correct** — original immutable, edits
  to final, the diff preserved as training signal.
- **Solo-operator maintainability** — a single non-expert operator can run,
  understand, and safely extend this.

A phase is GREEN only when **FLOOR = PASS** and **JUDGE = PASS**. Never advance a
phase on the builder's own say-so.

---

## Hard DON'T list

- Don't touch the **website repo** or the **enquiry Edge Function** — that's G2.
- Don't create/alter/write **`enquiries`** — read-only external.
- Don't set **`G_SEND`** or perform a **live send** — that's G-SEND (human only).
- Don't **hardcode** copy, timing, cadence, or send windows — placeholder +
  `sequence_config` only.
- Don't commit to **`main`** or auto-merge — open a PR (G3).
- Don't commit **secrets** — `.env` only, gitignored.
