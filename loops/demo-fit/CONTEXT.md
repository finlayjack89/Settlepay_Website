# demo-fit — durable context (read-only each run)

This is the bridge that carries design-time decisions into the cold-started loop.
The running loop does NOT have the chat this came from — everything it must
respect is pinned here. Read this top-to-bottom at the start of every run.

## What the loop is fixing
The illustrative payment demos render in small, variable-width boxes. At desktop
they're largely fine; the problems are **width-dependent** — cramped/awkwardly
wrapped text, split figures, and tight spacing at narrower demo-box widths. Goal:
every demo surface reads as a polished payment UI at every width, with no
horizontal overflow or clipped/mid-phrase-split text.

## Harvested decisions (from the design discussion — non-obvious, honour these)
- Demos are **fine at desktop**; don't "fix" what isn't broken. Focus narrow widths.
- **Mobile-capture gotcha:** playwright-cli navigation can reset the viewport.
  Always `resize` BEFORE and AFTER `open`, or you'll screenshot desktop by mistake.
- Test viewports **1280 / 540 / 390** map to demo boxes ~620 / ~500 / ~360px.
- The **CaseTheatre empty-pane bug** and the **Camber & Finch flow redesign** are
  **Problem 2 — OUT OF SCOPE** for this loop. If the floor check surfaces a blank
  pane / structural breakage, HALT to gate G2 and report; do NOT fix it here.

## Fix rubric (the only changes this loop may make)
Apply, per surface, as needed:
- Add `container-type: inline-size` to each demo's outer wrapper and convert its
  internal breakpoints to `@container` queries — adapt to the **demo's own box**,
  not the viewport.
- `min-width: 0` on flex/grid children that hold text (stops overflow).
- `white-space: nowrap` + `font-variant-numeric: tabular-nums` on amounts, sort
  codes, card numbers, references — figures must never wrap mid-value.
- `clamp()` for type that's too large in a small box; tighten line-height.
- Collapse 2-column splits to 1 column one box-width earlier.
- `text-wrap: balance`/`pretty` and consistent padding rhythm.

## Hard DON'T-TOUCH list
- **Files:** only `src/components/portfolio/**` and `src/styles/portfolio.css`.
  `kit-extras.css`/`styles.css` are shared — FLAG before editing, don't edit silently.
- **Copy:** sizing/spacing CSS only. Do not reword demo copy.
- **Brand palettes:** do not change any demo's colours. SettlePay blue (#3B82F6)
  must never become a demo brand accent.
- **Lockdales (real client):** `.lkd` is a faithful reconstruction of the real
  lockdalespayments.netlify.app page. Keep it faithful; bank numbers stay MASKED;
  no "fictional business" banner. Spacing fixes only.
- **Legal/brand:** no "Ltd"/company number, no "FCA authorised", no emoji — never
  introduce these while editing.

## Evaluator rubric (the JUDGE — a SEPARATE agent reviews screenshots, never the fixer)
For each surface × width, verdict **FITS** or **NEEDS-WORK** + specific notes:
- No text wrapping mid-phrase or to an awkward orphan line.
- Labels and their values sit on the intended lines; nothing overlaps.
- Amounts / refs never split across lines.
- Spacing is even; the box doesn't feel cramped or lopsided.
- Reads as a credible, polished payment UI at that width (sceptical 45–65 UK SMB owner).
The evaluator returns a machine-readable verdict the loop records in STATE; it does
NOT edit code.

## Verifier = floor + judge
- FLOOR (binary, deterministic): `loops/demo-fit/verify.sh` — build + per-surface
  overflow/clip + 0 console errors at all widths.
- JUDGE (separate agent): the evaluator rubric above on the screenshots.
- A surface is GREEN only when FLOOR passes AND JUDGE = FITS at all three widths.
