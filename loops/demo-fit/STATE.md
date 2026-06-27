# demo-fit — STATE (read + written every run)

This file is the loop's memory. The cold-started loop reads it to know what's
done and writes it after every iteration. Counters here are the ONLY brake the
budget can rely on.

started-at: (unset — set on first run)
last-run:   (none yet)
global-iterations: 0

## Per-surface progress
Legend: floor = verify.sh deterministic pass · judge = evaluator-agent FITS ·
each at widths 1280 / 540 / 390. A surface is GREEN only when floor AND judge pass
at all three. `rounds` = fix-rounds spent (budget: max 2).

| Surface | Page | floor (1280/540/390) | judge (1280/540/390) | rounds | green? |
|---|---|---|---|---|---|
| LockdalesCheckout (.lkd) | /work/lockdales-auctioneers/ | – / – / – | – / – / – | 0 | no |
| HarboursideCheckout (.mok) | /work/harbourside-lettings/ | – / – / – | – / – / – | 0 | no |
| Harbourside CaseTheatre (.ct) | /work/harbourside-lettings/ | – / – / – | – / – / – | 0 | no |
| Harbourside RoiCalculator (.roi) | /work/harbourside-lettings/ | – / – / – | – / – / – | 0 | no |
| MarshValeCheckout (.mok) | /work/marsh-vale-plumbing/ | – / – / – | – / – / – | 0 | no |
| MarshValeFlow (.mvf) | /work/marsh-vale-plumbing/ | – / – / – | – / – / – | 0 | no |
| MarshVale RoiCalculator (.roi) | /work/marsh-vale-plumbing/ | – / – / – | – / – / – | 0 | no |
| RowanCheckout (.mok) | /work/rowan-physiotherapy/ | – / – / – | – / – / – | 0 | no |
| Rowan CaseTheatre (.ct) | /work/rowan-physiotherapy/ | – / – / – | – / – / – | 0 | no |
| Rowan RoiCalculator (.roi) | /work/rowan-physiotherapy/ | – / – / – | – / – / – | 0 | no |
| StillwaterCheckout (.mok) | /work/stillwater-weddings/ | – / – / – | – / – / – | 0 | no |
| Stillwater CaseTheatre (.ct) | /work/stillwater-weddings/ | – / – / – | – / – / – | 0 | no |
| Stillwater RoiCalculator (.roi) | /work/stillwater-weddings/ | – / – / – | – / – / – | 0 | no |
| WhitmoreCheckout (.mok) | /work/whitmore-accountants/ | – / – / – | – / – / – | 0 | no |
| Whitmore CaseTheatre (.ct) | /work/whitmore-accountants/ | – / – / – | – / – / – | 0 | no |
| Whitmore RoiCalculator (.roi) | /work/whitmore-accountants/ | – / – / – | – / – / – | 0 | no |
| CamberFinchCheckout (.cf) | /work/camber-finch-auctions/ | – / – / – | – / – / – | 0 | no |
| Camber CaseTheatre (.ct) | /work/camber-finch-auctions/ | – / – / – | – / – / – | 0 | no |
| Camber RoiCalculator (.roi) | /work/camber-finch-auctions/ | – / – / – | – / – / – | 0 | no |
| BrandStudio (.bs) | /work/ | – / – / – | – / – / – | 0 | no |

## Anomalies surfaced (G2 — Problem 2, not fixed here)
(none yet)
