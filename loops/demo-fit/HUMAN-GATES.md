# demo-fit — human gates & budget (non-negotiable)

The loop may not pass any of these on its own authority. No self-approval.

## Gates
- **G0 — Pre-worktree (one-time).** The demos `LockdalesCheckout` and
  `CamberFinchCheckout` are uncommitted on `feat/enquiry-backend`. Commit (or
  stash→apply into the worktree) the pending demo work FIRST, then create the
  worktree from that commit — otherwise the worktree won't contain them.
  Human confirms the commit before the worktree is made.
- **G1 — Pre-first-run sign-off.** A human approves before the first fix round
  (confirm `verify.sh` runs and the worktree is correct).
- **G2 — Anomaly halt.** If the verifier surfaces a *structural* problem rather
  than a sizing one — a blank/empty theatre pane, the Camber & Finch flow being
  unclear, anything needing a redesign — STOP and surface it. That is **Problem 2,
  out of this loop's remit**; do not auto-fix. Also halt before touching shared CSS
  (`kit-extras.css`/`styles.css`) or any brand palette.
- **G3 — Merge gate.** The loop never commits to `main` and never merges. When the
  predicate is met it opens (or asks to open) a PR from the worktree branch; a
  human reviews and merges. Commits happen only when the user asks.

## Budget (hard stop — counted from STATE.md, not from session memory)
- **Max 2 fix-rounds per surface.** A surface still failing after 2 rounds is left
  as-is and reported — do not keep grinding it.
- **Max ~60 minutes wall-clock** from `started-at` in STATE.md.
- On hitting either ceiling: STOP, write the remaining red surfaces into STATE,
  and report. Do not continue "just one more."

## Spend
This loop spends model tokens (the fixer + the evaluator agent + playwright runs)
but calls no paid external API. There is no project spend-meter to register
against (static marketing site). If that changes, register usage before running.
