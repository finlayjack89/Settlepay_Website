---
name: demo-fit
description: Self-paced, self-verifying loop that audits and fixes the SettlePay illustrative payment demos for overflow / awkward wrapping / spacing across demo-box widths (1280/540/390), until every surface passes a deterministic floor AND a separate evaluator agent. Evaluator–optimizer pattern. Read CONTEXT.md and STATE.md first; never holds state in this file.
---

# demo-fit loop

> Durable logic (this file) is read-only each run. All changing progress lives in
> `loops/demo-fit/STATE.md`. This file never records progress.

## Each run

1. **Load context + state.** Read `loops/demo-fit/CONTEXT.md` (rules, rubric,
   don't-touch list) and `loops/demo-fit/STATE.md` (per-surface progress, round &
   iteration counts, started-at). Confirm you are in the **worktree** named in
   `TRIGGER.md`, on the loop branch — never on `main` or directly on a shared WIP
   branch.

2. **Budget check (hard stop).** From STATE: if wall-clock since started-at > 60 min
   OR any surface has had ≥ 2 fix-rounds and still isn't green, **STOP** and report
   the remaining failures (see `HUMAN-GATES.md` budget). Do not exceed.

3. **Pick the next surface.** From the `manifest.json` surfaces, choose the first
   that is not `{floor: pass, judge: pass}` at all three widths. If none remain →
   **predicate met**: announce done, summarise STATE, and point to gate **G3** (open
   a PR for human review — do NOT merge). Stop the loop.

4. **Audit.** With `playwright-cli`, screenshot the chosen surface at 1280 / 540 /
   390 (resize BEFORE and AFTER `open` — see CONTEXT gotcha). Note every overflow /
   wrap / cramp.

5. **Fix (optimizer).** Apply ONLY the CONTEXT fix rubric, ONLY in
   `src/components/portfolio/**` or `src/styles/portfolio.css`. Container queries
   first. If a fix would touch shared CSS or a brand palette, or you hit a
   structural bug (empty pane / Camber flow), **HALT to gate G2** — that's Problem 2,
   out of remit.

6. **Verify (floor).** Run `loops/demo-fit/verify.sh` (or pass a running preview
   URL). It must exit 0 for the floor to pass. Capture which cells failed.

7. **Judge (separate agent).** Spawn an evaluator **agent** (a distinct call, not
   your own reasoning) with the CONTEXT evaluator rubric + the new screenshots. It
   returns FITS / NEEDS-WORK + notes per width. The fixer never grades itself.

8. **Record.** Update `STATE.md`: floor + judge per width for this surface,
   increment its round count and the global iteration count, refresh `last-run`.
   Mark the surface green only if floor PASS and judge FITS at all three widths.

9. **Continue.** Move to the next surface. Self-pace via `/loop`. If the context
   window is filling mid-surface, `ScheduleWakeup` ~1200s and resume from STATE
   (the long fallback is for resuming across context windows, not for polling).

## Invariants
- Independent verifier always: `verify.sh` (deterministic) + evaluator agent (taste).
  Never advance a surface on the fixer's own say-so.
- Never commit to `main`. Never auto-merge. The PR is the human gate (G3).
- Never edit copy, brand colours, the Lockdales reconstruction's fidelity, or shared CSS without halting to a gate.
- All progress in STATE.md; if it's not in STATE, it didn't happen.
