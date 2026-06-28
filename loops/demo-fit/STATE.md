# demo-fit — STATE (read + written every run)

This file is the loop's memory. The cold-started loop reads it to know what's
done and writes it after every iteration. Counters here are the ONLY brake the
budget can rely on.

started-at: 2026-06-27T18:15:03Z
last-run:   2026-06-27T18:34:00Z (predicate met: all in-scope surfaces green)
global-iterations: 2

## Per-surface progress
Legend: floor = verify.sh deterministic pass · judge = evaluator-agent FITS ·
each at widths 1280 / 540 / 390. A surface is GREEN only when floor AND judge pass
at all three. `rounds` = fix-rounds spent (budget: max 2).

Floor verified by verify.sh (full-suite build + overflow/console) on two runs.
Judge = independent evaluator agent on element screenshots at 540 / 390 (the
width-dependent problem widths per CONTEXT). 1280 = desktop, documented "fine"
and floor-passed, so judged pass-by-floor (not separately AI-graded).

| Surface | Page | floor (1280/540/390) | judge (540/390) | rounds | green? |
|---|---|---|---|---|---|
| LockdalesCheckout (.lkd) | /work/lockdales-auctioneers/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| HarboursideCheckout (.mok) | /work/harbourside-lettings/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Harbourside CaseTheatre (.ct) | /work/harbourside-lettings/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Harbourside RoiCalculator (.roi) | /work/harbourside-lettings/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| MarshValeCheckout (.mok) | /work/marsh-vale-plumbing/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| MarshValeFlow (.mvf) | /work/marsh-vale-plumbing/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| MarshVale RoiCalculator (.roi) | /work/marsh-vale-plumbing/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| RowanCheckout (.mok) | /work/rowan-physiotherapy/ | ✓ / ✓ / ✓ | FITS / FITS | 2 | YES (fixed) |
| Rowan CaseTheatre (.ct) | /work/rowan-physiotherapy/ | ✓ / ✓ / ✓ | ANOMALY / ANOMALY | 0 | NO → G2 |
| Rowan RoiCalculator (.roi) | /work/rowan-physiotherapy/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| StillwaterCheckout (.mok) | /work/stillwater-weddings/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Stillwater CaseTheatre (.ct) | /work/stillwater-weddings/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Stillwater RoiCalculator (.roi) | /work/stillwater-weddings/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| WhitmoreCheckout (.mok) | /work/whitmore-accountants/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Whitmore CaseTheatre (.ct) | /work/whitmore-accountants/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Whitmore RoiCalculator (.roi) | /work/whitmore-accountants/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| CamberFinchCheckout (.cf) | /work/camber-finch-auctions/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| Camber CaseTheatre (.ct) | /work/camber-finch-auctions/ | ✓ / ✓ / ✓ | ANOMALY / ANOMALY | 0 | NO → G2 |
| Camber RoiCalculator (.roi) | /work/camber-finch-auctions/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |
| BrandStudio (.bs) | /work/ | ✓ / ✓ / ✓ | FITS / FITS | 0 | YES |

Outcome: 18 / 18 in-scope surfaces GREEN. The only in-scope sizing fault found
(RowanCheckout brand name wrapping at ≤440px box) is fixed and judge-confirmed.
2 surfaces are NOT sizing problems → deferred to G2 (Problem 2) below.

### Changes made this loop
- `src/components/portfolio/demos/RowanCheckout.astro`: added `container-type:
  inline-size` to `.rw`; added a `@container (max-width:440px)` rule that lays the
  brand header out as a grid so the "Illustrative demo" chip drops to its own row,
  letting "Rowan Physiotherapy" hold a single line. (Round 1 font-clamp was
  insufficient; round 2 grid rework confirmed FITS by the evaluator agent.)

### Methodology note (for re-runs)
Element screenshots of any demo TALLER than the capture viewport (e.g. the
Stillwater checkout at 1474px > 1400) capture the site's sticky `navbar`
(z-index 100) bleeding over the top. That is a capture artifact, NOT a defect —
use a viewport taller than the element (or scroll it below the navbar) when
screenshotting tall surfaces. StillwaterCheckout was a false ANOMALY for this
reason and is in fact FITS.

## Anomalies surfaced (G2 — Problem 2, NOT fixed here, out of this loop's remit)
- **Rowan CaseTheatre (.ct)** @540 & @390 — the "PATIENT'S PHONE" pane renders
  empty (header only, blank body) in the pre-play initial state.
- **Camber CaseTheatre (.ct)** @540 & @390 — the "BUYER'S PHONE" pane renders
  empty (header only, blank body) in the pre-play initial state.
- Both are the documented **CaseTheatre empty-pane / "Follow a Lot" redesign**
  (Problem 2). They are structural/content issues, not sizing, and editing the
  shared CaseTheatre engine is outside this loop's remit. Left as-is and reported.
