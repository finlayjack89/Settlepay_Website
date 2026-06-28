# outreach-build — launch contract

**Kind:** self-paced session loop → Claude Code primitive **`/loop` (no interval)**,
which paces itself with **`ScheduleWakeup`** between iterations / context-windows.
This is NOT a cron routine (`CronCreate`/`/schedule`) — it runs in a working
session, building phase by phase, and **stops at human gates**.

---

## Step 0 — clear gate G0, then make the worktree (one-time)

`outreach/` is independent of the website code, so build it on a branch off a
**fresh mainline**, in its own worktree, with a clean PR. Because the loop
scaffold doesn't exist on `origin/main` yet, copy it into the worktree.

```bash
# 0a. Fresh mainline
git fetch origin

# 0b. Dedicated worktree on a fresh loop branch off origin/main (clean PR base)
git worktree add -b feat/outreach-build ../worktrees/outreach-build origin/main

# 0c. Bring the loop scaffold into the worktree (it's not on main yet)
cp -R loops/outreach-build ../worktrees/outreach-build/loops/

# 0d. All work happens in ../worktrees/outreach-build from here on
cd ../worktrees/outreach-build
```

Then create `outreach/.env` (gitignored) with the keys below — **G0 human
confirms** the Supabase service-role connection and migration scope first:

```
DATABASE_URL=postgresql://...        # Supabase SERVICE-ROLE Postgres (server-side only)
COMPANIES_HOUSE_API_KEY=...
MILLIONVERIFIER_API_KEY=...
# Microsoft Graph (phase G, dry-run only until G-SEND):
GRAPH_TENANT_ID=... GRAPH_CLIENT_ID=... GRAPH_CLIENT_SECRET=... GRAPH_SENDER=...
# G_SEND is intentionally ABSENT — only a human ever sets it (gate G-SEND).
```

> Note: `verify.sh` resolves `outreach/` relative to its own location, so it
> targets the worktree copy automatically. To point it elsewhere, set
> `OUTREACH_DIR=/abs/path/to/outreach`.

---

## Step 1 — launch the loop (after gate G1 sign-off)

Run the `/loop` skill with **no interval** so it self-paces, pointing at this loop
from inside the worktree:

```
/loop run loops/outreach-build/SKILL.md from the ../worktrees/outreach-build
worktree: build the outreach pipeline phase by phase (manifest A→H) —
implement → verify.sh (floor) → separate judge agent → record to STATE → advance
only when floor PASS AND judge PASS, until every phase is GREEN or a HUMAN-GATE /
budget ceiling is hit. Re-read CONTEXT.md and STATE.md at the start of every
iteration. Build the drafting MECHANISM only; never invent conversion copy or
timing; never set G_SEND or send live email.
```

- On **first launch** the loop does G1 only (checks `.env`, runs `verify.sh`
  once, sets `started-at`) and **STOPS** for your sign-off. Approve, then relaunch
  the same command to begin building phase A.
- Pass that **same prompt** back on each `ScheduleWakeup` firing so the loop
  re-enters. (For an unattended re-entry sentinel the dynamic variant is
  `<<autonomous-loop-dynamic>>`, but this loop is user-launched and stops at
  gates, so you normally just relaunch the command.)
- **Cadence:** iterate continuously within a run (local build work, nothing
  external to poll). Only call `ScheduleWakeup(~1200s)` to resume after a
  context-window summary — a long fallback, never a 300s poll.

---

## Stop / done

- **Predicate met** (all phases A→H GREEN, `G_SEND` still unset, send path
  dry-run) → the loop announces done, summarises STATE, and opens / asks for a PR
  from `feat/outreach-build` (gate **G3**). It does **not** merge.
- **Gate hit** (G1/G2/G-SEND) → the loop STOPS and surfaces what it needs.
- **Budget hit** (2 fix-rounds on a phase, or 90 min) → the loop halts and reports
  the remaining red phases from STATE.md.

## Re-run later (the lasting value)

Any time the pipeline changes, relaunch the same `/loop` command — `verify.sh` +
the judge re-audit each phase and flag regressions. `STATE.md` is the source of
truth.
