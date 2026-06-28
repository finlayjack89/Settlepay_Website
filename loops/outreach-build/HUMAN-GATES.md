# outreach-build — human gates & budget (non-negotiable)

The loop may not pass any of these on its own authority. **No self-approval.**
This loop spends real money and can send real email, so the gates are stricter
than a code-only loop.

## Gates

- **G0 — Pre-worktree (one-time, human confirms).** Before the worktree is made:
  - Confirm `outreach/` is a **top-level folder in this repo** (decided) and that
    the phase-A migration will create everything **except `enquiries`**
    (`enquiries` is **read-only / external**, owned by the website Edge Function).
  - Confirm the Supabase **service-role** connection string is available for
    `outreach/.env` (server-side only — never the browser).
  - Confirm you accept the migration running against project
    `xqpbcoldcqfxfwhcqlcy`.

- **G1 — Pre-first-run sign-off (loop STOPS here on first launch).** A human
  approves before the first build round. On first run the loop only: confirms
  `outreach/.env` keys are present, runs `verify.sh` once to prove it executes,
  sets `started-at` in STATE, then halts for sign-off. **Register project spend
  before approving** (see Spend). Do not build on the first launch.

- **G2 — Anomaly halt (out of remit — surface, don't fix).** STOP and surface if:
  - the legal-structure classifier is genuinely ambiguous on a real
    `company_type` (suppress as a fail-safe, then surface);
  - the migration breaks or the schema conflicts with what's live;
  - anything requires touching the **website repo**, the **enquiry Edge
    Function**, or the **`enquiries`** table;
  - a phase appears to need a **conversion-strategy decision** (copy, tone,
    personalisation depth, follow-up timing, send windows, cadence) — that's the
    **DEFERRED drafting playbook**, not this loop's job.

- **G-SEND — Live-send gate (human-only; the loop CANNOT set it).** Live cold
  sending stays **disabled** until a human clears it, which requires **ALL THREE**:
  1. **domain warmup complete** on the separate sending domain
     (`settlepayhq.uk` or similar — never `@settlepay.uk`);
  2. a **documented Legitimate Interests Assessment (LIA)**;
  3. the **drafting playbook v1 researched and approved** (replacing the
     placeholder).
  Until then: `G_SEND` env unset, send path **dry-run / test-mailbox only**, and
  `sends.mode='live'` must remain 0. The floor fails if `G_SEND` is set.

- **G3 — Merge gate.** The loop makes **local checkpoint commits on
  `feat/outreach-build`** (one per green phase) so progress is durable and
  auditable — but it **never commits to `main`, never pushes, and never merges**.
  When all phases are GREEN it opens (or asks to open) a PR from the loop branch;
  a human reviews and merges. **Pushing** the branch and the **PR/merge** happen
  only when the user asks.

## Budget (hard stop — counted from STATE.md, not session memory)

- **Max 2 fix-rounds per phase.** A phase still red after 2 rounds is left as-is
  and reported — do not keep grinding it.
- **Max ~90 minutes wall-clock** per run, from `started-at` in STATE.md.
- On hitting either ceiling: STOP, write the remaining red phases into STATE, and
  report. Do not continue "just one more."

## Spend (this loop spends — register before running, per global §4)

- **Companies House** Advanced Search: free, but cap at **≤50 requests/run**
  during build (honour the ≤600 req / 5 min ceiling in code).
- **MillionVerifier**: paid. **Tiny samples only — ≤20 verifications/run** during
  build. No bulk verification without a gate.
- **LLM**: the **inline** provider is default (loop reasons on Claude Max → no API
  spend). The `api` provider is built but **not exercised** during build — keep
  paid LLM calls at **0** unless explicitly running an `api`-provider smoke test.
- **Email send**: **no live-send spend, ever, before G-SEND.** Dry-run /
  test-mailbox only.
- **Tracking:** there is no project spend-meter in this static-site repo today.
  Before first run, record where outreach spend is tracked (Companies House key
  usage, MillionVerifier credits, Anthropic API once the `api` provider is live,
  Microsoft Graph). An unregistered paid loop is invisible, mis-attributed cost.
  Update STATE's "Spend this run" counters every iteration.
