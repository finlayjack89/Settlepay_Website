# demo-fit — launch contract

**Kind:** self-paced session loop → Claude Code primitive **`/loop` (no interval)**,
which paces itself with **`ScheduleWakeup`** between iterations/context-windows.
This is NOT a cron routine (`CronCreate`/`/schedule`) — it runs in a working
session, not on a calendar.

## Step 0 — clear gate G0, then make the worktree (one-time)
```bash
# 1. Commit the pending demo work so the worktree includes it (human-approved, G0)
git add -A && git commit -m "wip: lockdales + camber demos before demo-fit loop"

# 2. Dedicated worktree on a fresh loop branch off the current tip
git worktree add -b fix/demo-fit ../worktrees/demo-fit HEAD

# 3. Work happens in ../worktrees/demo-fit from here on
cd ../worktrees/demo-fit && npm install   # if node_modules isn't shared
```

## Step 1 — launch the loop (after gate G1 sign-off)
Run the `/loop` skill with **no interval** so it self-paces, pointing at this loop:

```
/loop run loops/demo-fit/SKILL.md from the ../worktrees/demo-fit worktree:
audit→fix→verify each demo surface until STATE.md shows every surface green on
both the floor (verify.sh) and the evaluator agent, or the HUMAN-GATES budget is
hit. Re-read CONTEXT.md and STATE.md at the start of every iteration.
```

- Pass that **same prompt** back on each `ScheduleWakeup` firing so the loop re-enters.
- For an unattended re-entry sentinel use the dynamic variant: `ScheduleWakeup`
  with the literal `<<autonomous-loop-dynamic>>` prompt is NOT needed here — this
  loop is user-launched and self-terminating on the predicate/budget.
- **Cadence:** iterate continuously within a run (local work, nothing to wait on).
  Only call `ScheduleWakeup(~1200s)` if you must resume after a context-window
  summary — long fallback, never a 300s poll.

## Stop / done
- Predicate met (all surfaces green) → loop announces done and opens/asks for a PR
  from `fix/demo-fit` (gate **G3**). It does not merge.
- Budget hit → loop halts and reports remaining red surfaces from STATE.md.

## Re-run later (the lasting value)
Any time the demos change, relaunch the same `/loop` command — `verify.sh` + the
evaluator re-audit everything and flag regressions. STATE.md is the source of truth.
