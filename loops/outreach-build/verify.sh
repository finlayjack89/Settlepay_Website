#!/usr/bin/env bash
# outreach-build verifier — the deterministic FLOOR (binary verdict).
# Independent of the loop's reasoning: it asserts the current phase's GREEN
# predicate via pytest + read-only SQL (floor_db.py) + file/grep checks. It does
# NOT judge PECR nuance or mechanism cleanliness — that's the separate judge agent.
#
# Usage:
#   loops/outreach-build/verify.sh        # phase read from STATE.md (current-phase:)
#   loops/outreach-build/verify.sh C      # force a phase (runs cumulative A..C)
#
# Exit: 0 = FLOOR PASS for the target phase (and all earlier) · non-zero = FAIL
#       (lists the failing checks by name).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${OUTREACH_DIR:-$ROOT/outreach}"        # outreach/ in this worktree
STATE="$HERE/STATE.md"
fails=()

# ---- phase resolution ----
PHASE="${1:-}"
if [ -z "$PHASE" ]; then
  PHASE="$(grep -iE '^current-phase:' "$STATE" 2>/dev/null | head -1 \
           | sed -E 's/.*:[[:space:]]*([A-Ha-h]).*/\1/')"
fi
PHASE="$(printf '%s' "${PHASE:-A}" | tr '[:lower:]' '[:upper:]')"
echo "▶ FLOOR for phase $PHASE (cumulative A..$PHASE)  outreach=$OUT"

# ---- load .env for read-only DB asserts (never echo secrets) ----
if [ -f "$OUT/.env" ]; then set -a; . "$OUT/.env"; set +a; fi

# ---- python: prefer the project venv (deps live there), else system python3 ----
PY="python3"; [ -x "$OUT/.venv/bin/python" ] && PY="$OUT/.venv/bin/python"

# ---- helpers ----
ok(){ echo "  ✓ $1"; }
nf(){ fails+=("$1"); echo "  ✗ $1"; }

# scalar read-only query -> integer, or 'x' on any error/empty
num(){
  local v; v="$("$PY" "$HERE/floor_db.py" scalar "$1" 2>/dev/null)"
  if [[ "$v" =~ ^-?[0-9]+$ ]]; then echo "$v"; else echo "x"; fi
}
expect_eq(){ local v; v="$(num "$2")"; if [ "$v" != x ] && [ "$v" -eq "$3" ]; then ok "$1 (=$v)"; else nf "$1 (got '$v', need =$3)"; fi; }
expect_ge(){ local v; v="$(num "$2")"; if [ "$v" != x ] && [ "$v" -ge "$3" ]; then ok "$1 ($v >= $3)"; else nf "$1 (got '$v', need >= $3)"; fi; }
expect_lt(){ local v; v="$(num "$2")"; if [ "$v" != x ] && [ "$v" -lt "$3" ]; then ok "$1 ($v < $3)"; else nf "$1 (got '$v', need < $3)"; fi; }

run_pytest(){  # $1 marker  $2 label
  if [ ! -d "$OUT" ]; then nf "$2 (outreach/ missing)"; return; fi
  if [ ! -x "$PY" ] && ! command -v "$PY" >/dev/null 2>&1; then nf "$2 ($PY missing)"; return; fi
  if (cd "$OUT" && "$PY" -m pytest -q -m "$1" >/tmp/outreach-floor-pytest.log 2>&1); then
    ok "$2"
  else
    nf "$2 (pytest -m $1 failed — /tmp/outreach-floor-pytest.log)"
  fi
}

# leads that are still in a contactable state (anything not suppressed/rejected/discarded)
CONTACTABLE="('discovered','enriched','drafted','awaiting_approval','approved','sending','sent','replied')"

# ---- cross-cutting (every phase) ----
crosscut(){
  if [ ! -d "$OUT" ]; then nf "xc: outreach/ does not exist yet"; return; fi
  if git -C "$ROOT" ls-files --error-unmatch outreach/.env >/dev/null 2>&1; then
    nf "xc: outreach/.env is git-tracked (must be gitignored)"
  else ok "xc: .env not tracked"; fi
  if git -C "$ROOT" grep -nIE 'service_role|SUPABASE_SERVICE_ROLE|eyJ[A-Za-z0-9_-]{30,}' \
       -- outreach ':!outreach/.env*' ':!outreach/**/*.example' >/dev/null 2>&1; then
    nf "xc: possible secret literal in tracked outreach files"
  else ok "xc: no obvious secret literals tracked"; fi
}

# ---- phase checks ----
check_A(){
  echo "— A Foundations"
  [ -d "$OUT" ] && ok "A: outreach/ exists" || { nf "A: outreach/ missing"; return; }
  (cd "$OUT" && "$PY" -c "import outreach" >/dev/null 2>&1) && ok "A: package imports" || nf "A: 'import outreach' fails"
  ls "$OUT"/migrations/*.sql >/dev/null 2>&1 || ls "$OUT"/**/migrations/*.sql >/dev/null 2>&1 \
    && ok "A: migration file present" || nf "A: no migrations/*.sql found"
  expect_ge "A: DB connects"                 "SELECT 1" 1
  expect_eq "A: enums lead_state+subscriber_class present (outreach schema)" \
    "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='outreach' AND t.typname IN ('lead_state','subscriber_class')" 2
  expect_eq "A: drafts has body_original+body_final" \
    "SELECT count(*) FROM information_schema.columns WHERE table_schema='outreach' AND table_name='drafts' AND column_name IN ('body_original','body_final')" 2
  run_pytest "floor_a" "A: state-machine + audit_log unit tests"
}

check_B(){
  echo "— B find_leads"
  expect_ge "B: ≥30 discovered leads"         "SELECT count(*) FROM leads WHERE state='discovered'" 30
  expect_eq "B: no duplicate company_number"  "SELECT count(*)-count(DISTINCT company_number) FROM leads" 0
  expect_eq "B: no null key fields"           "SELECT count(*) FROM leads WHERE company_number IS NULL OR company_name IS NULL" 0
  run_pytest "floor_b" "B: rate-limit guard test"
}

check_C(){
  echo "— C compliance firewall (PECR)"
  run_pytest "floor_c" "C: classifier fixtures"
  expect_eq "C: 0 individual|unknown in a contactable state" \
    "SELECT count(*) FROM leads WHERE subscriber_class IN ('individual','unknown') AND state IN $CONTACTABLE" 0
  expect_eq "C: every lead has a lawful_basis audit row" \
    "SELECT count(*) FROM leads l WHERE NOT EXISTS (SELECT 1 FROM audit_log a WHERE a.company_number=l.company_number AND a.lawful_basis='legitimate interests')" 0
  # never cold-contact an existing inbound enquirer: a contactable cold lead whose
  # discovered email matches the website's inbound source (public.<ENQUIRY_SOURCE_TABLE>)
  expect_eq "C: no contactable lead matches an inbound enquirer" \
    "SELECT count(*) FROM outreach.leads l JOIN outreach.enrichment e ON e.company_number=l.company_number JOIN public.${ENQUIRY_SOURCE_TABLE:-leads} q ON lower(e.contact_email)=lower(q.email) WHERE l.state IN $CONTACTABLE" 0
}

check_D(){
  echo "— D enrich_company"
  expect_ge "D: ≥1 enriched (website+signal)" \
    "SELECT count(*) FROM enrichment WHERE website IS NOT NULL AND signal IS NOT NULL" 1
  expect_ge "D: ≥1 verified contact email" \
    "SELECT count(*) FROM enrichment WHERE contact_email IS NOT NULL AND email_verified IS TRUE" 1
  expect_eq "D: no contactable lead keeps an unverifiable email" \
    "SELECT count(*) FROM leads l JOIN enrichment e ON e.company_number=l.company_number WHERE e.email_verified IS FALSE AND l.state IN $CONTACTABLE" 0
  run_pytest "floor_d" "D: enrichment unit tests"
}

check_E(){
  echo "— E draft_email (mechanism only)"
  local pf="$OUT/prompts/draft_email.md"
  if [ -f "$pf" ] && grep -qi 'PLACEHOLDER' "$pf"; then ok "E: prompts/draft_email.md present & marked PLACEHOLDER"
  else nf "E: prompts/draft_email.md missing or not marked PLACEHOLDER"; fi
  expect_ge "E: ≥1 draft written to body_original" \
    "SELECT count(*) FROM drafts WHERE body_original IS NOT NULL AND length(btrim(body_original))>0" 1
  expect_lt "E: all body_original under 125 words" \
    "SELECT coalesce(max(array_length(regexp_split_to_array(btrim(body_original),'\s+'),1)),999) FROM drafts WHERE body_original IS NOT NULL" 125
  expect_eq "E: every draft has an unsubscribe line" \
    "SELECT count(*) FROM drafts WHERE body_original IS NOT NULL AND body_original NOT ILIKE '%unsubscribe%'" 0
  expect_eq "E: every draft has SettlePay sender ID" \
    "SELECT count(*) FROM drafts WHERE body_original IS NOT NULL AND body_original NOT ILIKE '%settlepay%'" 0
  expect_eq "E: every draft references FCA-regulated partners" \
    "SELECT count(*) FROM drafts WHERE body_original IS NOT NULL AND body_original NOT ILIKE '%fca-regulated partner%'" 0
  expect_eq "E: ZERO links/images in any draft" \
    "SELECT count(*) FROM drafts WHERE body_original ~* '(https?://|www\.|!\[|\]\(|<img|<a )'" 0
  run_pytest "floor_e" "E: structural reviewer unit tests"
}

check_F(){
  echo "— F approval queue"
  # immutability of body_original + 'no advance without a recorded decision' are
  # behavioural — asserted by the pytest below (the floor stays schema-agnostic).
  run_pytest "floor_f" "F: edit→body_final / approve→copy / body_original immutable / decision-required tests"
  expect_eq "F: no approved/sent draft with empty body_final" \
    "SELECT count(*) FROM drafts WHERE status IN ('approved','sent') AND (body_final IS NULL OR length(btrim(body_final))=0)" 0
}

check_G(){
  echo "— G send (hard-gated, dry-run only)"
  case "${G_SEND:-}" in
    1|true|TRUE|yes|on) nf "G: G_SEND is set — the loop must NEVER enable live send (human-only gate)";;
    *) ok "G: G_SEND unset (live send disabled)";;
  esac
  expect_eq "G: 0 live sends recorded during build" \
    "SELECT count(*) FROM sends WHERE mode='live'" 0
  run_pytest "floor_g" "G: dry-run send + refuse-while-gated + cap + suppression + kill-switch tests"
}

check_H(){
  echo "— H operational wiring"
  # no hardcoded timing: timedelta(days/hours/minutes=<n>) or sleep(<n>) outside the config module
  if grep -RInE 'timedelta\((days|hours|minutes|weeks)=[0-9]' "$OUT" --include='*.py' \
       | grep -viE '(sequence_config|/config/|config\.py)' >/dev/null 2>&1; then
    nf "H: hardcoded timedelta delay found outside sequence_config"
  else ok "H: no hardcoded timedelta delays outside config"; fi
  if grep -RInE '(time\.)?sleep\([0-9]' "$OUT" --include='*.py' \
       | grep -viE '(sequence_config|/config/|config\.py|test)' >/dev/null 2>&1; then
    nf "H: hardcoded sleep() delay found outside config/tests"
  else ok "H: no hardcoded sleep() delays outside config/tests"; fi
  grep -RIl -iE 'kill[_ ]?switch' "$OUT" --include='*.py' >/dev/null 2>&1 \
    && ok "H: kill switch present" || nf "H: no kill switch found"
  grep -RIl -iE 'graduat|threshold' "$OUT" >/dev/null 2>&1 \
    && ok "H: graduation thresholds present in config" || nf "H: no graduation thresholds found"
  if (cd "$OUT" && "$PY" -m outreach run --stage all --dry-run >/tmp/outreach-run.log 2>&1); then
    ok "H: \`run --stage all --dry-run\` exits 0"
  else nf "H: \`run --stage all --dry-run\` failed — /tmp/outreach-run.log"; fi
  run_pytest "floor_h" "H: one-step-per-tick + config-driven timing tests"
}

# ---- cumulative dispatch: crosscut once, then A..PHASE in order ----
crosscut
for p in A B C D E F G H; do
  "check_$p"
  [ "$p" = "$PHASE" ] && break
done

echo
if [ ${#fails[@]} -eq 0 ]; then
  echo "FLOOR: PASS (phase $PHASE)"; exit 0
else
  echo "FLOOR: FAIL (phase $PHASE) — ${#fails[@]} failing check(s):"
  printf '  - %s\n' "${fails[@]}"
  exit 1
fi
