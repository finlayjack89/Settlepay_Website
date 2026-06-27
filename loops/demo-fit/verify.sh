#!/usr/bin/env bash
# demo-fit verifier — the deterministic FLOOR check (binary verdict).
# Independent of the loop's reasoning: it builds, serves, and measures real
# layout in a real browser. It does NOT judge taste (that's the evaluator agent).
#
# Usage:
#   loops/demo-fit/verify.sh            # builds + serves preview on :4399, checks, tears down
#   loops/demo-fit/verify.sh <BASE_URL> # check an already-running server (e.g. dev/preview)
#
# Exit codes: 0 = FLOOR PASS (all surfaces, all widths) · 1 = build failed · 2 = layout/console FAIL
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

BASE_URL="${1:-}"
WIDTHS=(1280 540 390)
PAGES=(
  /work/lockdales-auctioneers/ /work/harbourside-lettings/ /work/marsh-vale-plumbing/
  /work/rowan-physiotherapy/ /work/stillwater-weddings/ /work/whitmore-accountants/
  /work/camber-finch-auctions/ /work/
)
fail=0

echo "▶ build"
if ! npm run build >/tmp/demo-fit-build.log 2>&1; then
  echo "✗ build failed — see /tmp/demo-fit-build.log"; exit 1
fi
echo "✓ build"

STARTED=""
if [ -z "$BASE_URL" ]; then
  npm run preview -- --port 4399 >/tmp/demo-fit-preview.log 2>&1 &
  SRV=$!; STARTED=1; BASE_URL="http://localhost:4399"
  for _ in $(seq 1 30); do curl -fsS -o /dev/null "$BASE_URL/work/" && break; sleep 1; done
fi
cleanup() { [ -n "$STARTED" ] && kill "$SRV" 2>/dev/null; playwright-cli close >/dev/null 2>&1 || true; }
trap cleanup EXIT

# Returns JSON: pageOverflow (page scrolls horizontally) + bad[] (demo roots that
# overflow themselves, or descendants escaping their demo root's right edge).
OVERFLOW_JS='(() => {
  const vw = innerWidth;
  const pageOverflow = document.documentElement.scrollWidth > vw + 1;
  const bad = [];
  document.querySelectorAll(".mok,.lkd,.cf,.ct,.mvf,.roi,.bs").forEach((r) => {
    if (r.scrollWidth > r.clientWidth + 1) bad.push(((r.className||"")+"").split(" ").filter(Boolean)[0] + ":self");
    const rb = r.getBoundingClientRect();
    r.querySelectorAll("*").forEach((el) => {
      const b = el.getBoundingClientRect();
      if (b.width && b.right > rb.right + 1) bad.push(((el.className||el.tagName)+"").split(" ").filter(Boolean)[0] + ":child");
    });
  });
  return JSON.stringify({ pageOverflow, bad: [...new Set(bad)].slice(0, 15) });
})()'

for url in "${PAGES[@]}"; do
  for w in "${WIDTHS[@]}"; do
    playwright-cli resize "$w" 1400 >/dev/null 2>&1
    playwright-cli open "$BASE_URL$url" >/dev/null 2>&1
    playwright-cli resize "$w" 1400 >/dev/null 2>&1   # re-assert: navigation can reset viewport
    res=$(playwright-cli --raw eval "$OVERFLOW_JS" 2>/dev/null | tail -1)
    errs=$(playwright-cli console 2>/dev/null | grep -oE "Errors: [0-9]+" | grep -oE "[0-9]+" | tail -1)
    bad_cell=0
    echo "$res" | grep -q '"pageOverflow":true' && bad_cell=1
    echo "$res" | grep -q '"bad":\["' && bad_cell=1
    [ "${errs:-0}" != "0" ] && bad_cell=1
    if [ "$bad_cell" = "1" ]; then echo "✗ ${url} @${w}  ${res}  console=${errs:-0}"; fail=1
    else echo "✓ ${url} @${w}"; fi
  done
done

if [ "$fail" = "0" ]; then echo "FLOOR: PASS"; exit 0; else echo "FLOOR: FAIL"; exit 2; fi
