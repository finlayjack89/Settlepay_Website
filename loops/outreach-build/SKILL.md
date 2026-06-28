---
name: outreach-build
description: Self-paced, self-verifying build loop that implements SettlePay's UK PECR-compliant agentic cold-email pipeline in outreach/ phase by phase (A→H), driving each phase to GREEN on a deterministic floor (verify.sh) AND a separate judge agent, until the pipeline infrastructure is built and live sending sits behind human gate G-SEND. Evaluator–optimizer pattern. Builds the drafting MECHANISM only — conversion copy/timing is DEFERRED, out of remit. Read CONTEXT.md and STATE.md first; never holds state in this file.
---

# outreach-build loop

> Durable logic (this file) is read-only each run. All changing progress lives in
> `loops/outreach-build/STATE.md` + `iterations.jsonl`. This file never records
> progress. The loop builds the drafting **mechanism only** — never conversion
> copy or timing (that's DEFERRED; see CONTEXT.md).

## Each run

1. **Load context + state.** Read `loops/outreach-build/CONTEXT.md` (stack,
   invariants, firewall, deferred remit, the verbatim draft placeholder, judge
   rubric), `loops/outreach-build/manifest.json` (phases + GREEN predicates), and
   `loops/outreach-build/STATE.md` (current phase, per-phase floor/judge/rounds,
   counters). Confirm you are in the **worktree** named in `TRIGGER.md`, on the
   loop branch — **never `main`**, never the website's branch.

2. **Gate G1 (first launch only).** If `started-at` in STATE is unset, this is
   the first run: confirm `outreach/.env` has the needed keys, run `verify.sh`
   once to prove it executes, set `started-at`, then **STOP and hand to the human
   for G1 sign-off** (see HUMAN-GATES). Do not build on the first launch.

3. **Budget check (hard stop, from STATE — not session memory).** If wall-clock
   since `started-at` > 90 min, OR the current phase has had ≥ 2 fix-rounds and is
   still not GREEN → **STOP** and report the failing checks (HUMAN-GATES budget).
   Do not exceed.

4. **Pick the phase.** From `manifest.json`, the current phase is the first that
   is not `{floor: PASS, judge: PASS}`. If **all A→H are GREEN** → **predicate
   met**: announce done, summarise STATE, confirm `G_SEND` is still unset and the
   send path is dry-run only, and point to gate **G3** (open / ask for a PR from
   the loop branch — do **NOT** merge). Stop the loop.

5. **Implement (optimizer).** Build the current phase to its manifest GREEN
   predicate, honouring every CONTEXT invariant. Mechanism only.
   - Phase E: write `outreach/prompts/draft_email.md` **verbatim** from CONTEXT —
     do not author real copy.
   - If the phase appears to need a **conversion-strategy decision** (what to say,
     when/how often to send, cadence) → that's DEFERRED → **halt to G2**.
   - If you hit classifier ambiguity on a real `company_type`, a migration
     breakage, or **any** need to touch the website repo / Edge Function /
     `enquiries` table → **halt to G2**.
   - Never set `G_SEND`; never perform a live send; never commit secrets.

6. **Verify (floor).** Run `loops/outreach-build/verify.sh` (it reads the current
   phase from STATE, or pass it explicitly, e.g. `verify.sh C`). It must exit 0
   for the floor to pass. Capture which checks failed.

7. **Judge (separate agent).** Spawn an evaluator **agent** — a distinct `Agent`
   call, NOT your own reasoning — with the CONTEXT judge rubric + this phase's
   diff/output. It returns **PASS / NEEDS-WORK + notes**. The builder never grades
   itself. (Phase E especially: the judge confirms the placeholder is clearly
   marked and **no conversion strategy was invented**.)

8. **Record.** Update `STATE.md`: floor verdict + judge verdict for this phase,
   increment its `rounds`, bump `global-iterations`, refresh `last-run`, set
   `current-phase`. Append one line to `iterations.jsonl`
   (`{ts, phase, round, floor, judge, notes}`). Mark the phase GREEN **only** when
   floor = PASS and judge = PASS.

9. **Checkpoint + advance (or fix).** If GREEN → **commit the phase on
   `feat/outreach-build`** (`feat(outreach): phase X green`; include code +
   STATE.md + iterations.jsonl — **never `main`, never push**; push/PR stay at
   G3) so progress survives a context-window resume, then move to the next phase.
   If not GREEN and rounds < 2 → apply the floor/judge notes and retry (same
   phase). If rounds = 2 and still red → leave it, record it, STOP per budget.
   Self-pace via `/loop`; if the context window is filling **mid-phase**, write a
   one-line "Notes / handoff" in STATE (what's built, what's next),
   `ScheduleWakeup(~1200s)` and resume from STATE + the worktree files (long
   fallback for resuming across context windows — never a 300s poll; there's
   nothing external to poll).

## Invariants (also enforced by the floor + judge — see CONTEXT)

- Independent verifier always: `verify.sh` (deterministic floor) + a **separate**
  judge agent. Never advance a phase on the builder's own say-so.
- **No live send without G-SEND** (human-only); the loop never sets `G_SEND`;
  send path stays dry-run / test-mailbox.
- **Mechanism only** — never invent conversion copy or timing.
- **Individual/unknown subscribers never contactable**; `check_suppression`
  (suppressions ∪ enquiries) before any send.
- **`body_original` immutable**; edits go to `body_final`.
- Checkpoint commits ON `feat/outreach-build` are expected (one per green phase);
  but never commit to `main`, never push, never auto-merge — pushing + the PR are
  the human gate (G3).
- Secrets only in `outreach/.env`, never committed.
- All progress in STATE.md / iterations.jsonl; if it's not in STATE, it didn't
  happen.
