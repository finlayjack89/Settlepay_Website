#!/usr/bin/env bash
# Deploy the SettlePay ops platform to Cloud Run — ON-DEMAND mode.
#
#   ops/deploy-cloudrun.sh bootstrap   # one-off: APIs, Artifact Registry, secrets
#   ops/deploy-cloudrun.sh build       # Cloud Build -> Artifact Registry (no local docker)
#   ops/deploy-cloudrun.sh deploy      # deploy/update the Cloud Run service
#   ops/deploy-cloudrun.sh secret NAME # set/rotate one secret (value read from stdin)
#   ops/deploy-cloudrun.sh rewrite     # print the vercel.json rewrite for settlepay.uk/dashboard
#   ops/deploy-cloudrun.sh schedule    # OPTIONAL (live phase): Cloud Scheduler -> POST /tick
#   ops/deploy-cloudrun.sh rollback    # route traffic back to the previous revision
#
# Mode: min-instances=0 (scale to zero — the platform runs when the operator opens
# it; idle cost ~ £0) with instance-based billing (--no-cpu-throttling) so the
# in-process JobRunner keeps CPU while the instance is warm. Add `schedule` only
# when going live: domain warm-up needs steady daily volume, not bursts.
#
# Requires: gcloud authenticated (gcloud auth login) against GCLOUD_PROJECT.
# The Gmail OAuth CLIENT lives in a separate settlepay.uk Workspace-org project
# (Internal consent = durable refresh token); only its credential VALUES land here
# as secrets. Hosting project and OAuth project are deliberately decoupled.
set -euo pipefail

PROJECT="${GCLOUD_PROJECT:?set GCLOUD_PROJECT to your hosting project id}"
REGION="${GCLOUD_REGION:-europe-west2}"
SERVICE="${OPS_SERVICE:-settlepay-ops}"
REPO="${OPS_REPO:-settlepay-ops}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REPO/console:latest"
BASE_PATH="${OPS_BASE_PATH:-/dashboard}"
# Dedicated least-privilege runtime identity: may read exactly the SECRETS below, nothing else.
RUN_SA="settlepay-ops-run@$PROJECT.iam.gserviceaccount.com"

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$OPS_DIR/.." && pwd)"   # the outreach/ project dir (build context)

# Secret Manager names consumed by the service (values are set via `secret`).
SECRETS=(DATABASE_URL COMPANIES_HOUSE_API_KEY MILLIONVERIFIER_API_KEY
         REOON_API_KEY ZEROBOUNCE_API_KEY
         FIRECRAWL_API_KEY ANTHROPIC_API_KEY GOOGLE_MAPS_API_KEY
         # the critic only, and deliberately a DIFFERENT provider from the drafter:
         # a judge from the generator's own family shares its blind spots
         OPENAI_API_KEY
         GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
         GOOGLE_REFRESH_TOKEN CONSOLE_PASSWORD_HASH SESSION_SECRET)

# Non-secret runtime config, applied with --update-env-vars (a MERGE).
#
# This used to use --set-env-vars, which REPLACES the entire env block: a routine
# image deploy silently reverted INBOUND_SOURCE to inline, dropped OPERATOR_EMAIL,
# and — worst — dropped TICK_INVOKER_SA/TICK_AUDIENCE, which makes every Cloud
# Scheduler tick 401 and stops the pipeline dead with nothing in the deploy output
# saying so. Merging means a deploy can no longer un-configure a running service.
# To REMOVE a var, do it explicitly: gcloud run services update --remove-env-vars NAME
#
# The merge alone was NOT enough. A var written as `NAME=${NAME:-default}` is always
# present in the merge, so an unset shell variable still OVERWRITES the running
# service with the default — which is how a deploy silently put INBOUND_SOURCE back
# to `inline` after it had been turned on, muting bounce/opt-out ingestion with
# nothing in the output saying so. The merge only protects vars the deploy DOESN'T
# mention. Hence the split below.

# 1. BUILD-TIME config — tracks the code, so the deploy legitimately owns it and
#    re-asserting it on every deploy is correct.
ENV_VARS="BASE_PATH=$BASE_PATH,DB_SCHEMA=outreach,ENQUIRY_SOURCE_TABLE=leads"
# Gemini promoted after the drafting bench (gemini-3-flash-preview won 4-2 + 3x cheaper).
# Draws the GCP credit; signal/ICP use gemini-3.1-flash-lite, drafting gemini-3-flash-preview.
ENV_VARS+=",LLM_PROVIDER=gemini,WEBSITE_RESOLVER=firecrawl"
ENV_VARS+=",GEMINI_PROJECT=$PROJECT"

# 2. OPERATIONAL STATE — a human owns these, and a code deploy must never move them.
#    Emitted ONLY when explicitly set for this invocation; otherwise omitted, so the
#    merge leaves whatever the operator last set on the service untouched. Each has a
#    safe default in config.py, so an omitted var is never an undefined one.
#    To change one:  PIPELINE_AUTONOMOUS=1 ops/deploy-cloudrun.sh deploy
#              or:   gcloud run services update ... --update-env-vars NAME=value
#    (`if`, not `[ … ] && …`: under `set -e` a false test as the last statement in the
#    loop body would abort the deploy on the first unset var.)
for v in PIPELINE_AUTONOMOUS PLACES_PER_TICK INBOUND_SOURCE CREDIT_START_DATE \
         GMAIL_SENDER OPERATOR_EMAIL; do
  if [ -n "${!v:-}" ]; then ENV_VARS+=",$v=${!v}"; fi
done
# G_SEND is deliberately absent from that list and from this script: live sending is
# cleared by a human on the service, never by a deploy.

cmd="${1:-}"

case "$cmd" in
  bootstrap)
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
      artifactregistry.googleapis.com secretmanager.googleapis.com \
      cloudscheduler.googleapis.com aiplatform.googleapis.com --project "$PROJECT"
    gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" \
      >/dev/null 2>&1 || gcloud artifacts repositories create "$REPO" \
      --repository-format docker --location "$REGION" --project "$PROJECT"
    for s in "${SECRETS[@]}"; do
      gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1 || {
        echo "creating empty secret $s — set it with: ops/deploy-cloudrun.sh secret $s"
        printf 'CHANGE-ME' | gcloud secrets create "$s" --data-file=- --project "$PROJECT"
      }
    done
    gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT" >/dev/null 2>&1 || \
      gcloud iam service-accounts create settlepay-ops-run \
        --display-name "settlepay-ops Cloud Run runtime" --project "$PROJECT"
    for s in "${SECRETS[@]}"; do
      gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:$RUN_SA" \
        --role roles/secretmanager.secretAccessor --project "$PROJECT" --quiet >/dev/null
    done
    # Gemini via Vertex AI runs as the runtime SA (no key — ADC on Cloud Run).
    gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$RUN_SA" \
      --role roles/aiplatform.user --condition=None --quiet >/dev/null
    echo "bootstrap done. Set each secret, then: build && deploy"
    ;;

  secret)
    name="${2:?usage: deploy-cloudrun.sh secret NAME  (value on stdin)}"
    echo "paste the value for $name then Ctrl-D:"
    gcloud secrets versions add "$name" --data-file=- --project "$PROJECT"
    ;;

  build)
    gcloud builds submit "$SRC_DIR" --tag "$IMAGE" --project "$PROJECT"
    ;;

  deploy)
    args=(--image "$IMAGE" --region "$REGION" --project "$PROJECT"
          --service-account "$RUN_SA"
          --allow-unauthenticated       # app-level login guards the console
          --min-instances 0 --max-instances 1
          --no-cpu-throttling           # JobRunner keeps CPU while warm
          --memory 512Mi --cpu 1 --timeout 300
          --update-env-vars "$ENV_VARS")   # MERGE — never blank a running service's config
    # Attach only the secrets that actually EXIST. An optional integration that has not
    # been provisioned yet must not break the deploy of everything else: adding
    # OPENAI_API_KEY to the list above (for the draft critic) failed the whole revision
    # with "Permission denied on secret", which reads like a broken IAM grant rather than
    # "you have not created that key yet". The code already degrades cleanly when a key is
    # absent — the deploy should too.
    missing=()
    for s in "${SECRETS[@]}"; do
      if gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1; then
        args+=(--update-secrets "$s=$s:latest")
      else
        missing+=("$s")
      fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
      # --update-secrets is a MERGE, so simply omitting one leaves any reference the
      # service already carries in place — including one left behind by an earlier failed
      # attempt, which then fails every subsequent deploy with the same misleading
      # "Permission denied" until it is explicitly removed.
      for s in "${missing[@]}"; do
        args+=(--remove-secrets "$s")
      done
      echo "NOTE: not configured, skipped: ${missing[*]}"
      echo "      set one with: ops/deploy-cloudrun.sh secret <NAME>   # value on stdin"
    fi
    gcloud run deploy "$SERVICE" "${args[@]}"
    url="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
    echo ""
    echo "Deployed: $url$BASE_PATH/"
    echo "Next: ops/deploy-cloudrun.sh rewrite   # wire settlepay.uk/dashboard"
    ;;

  rewrite)
    url="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
    cat <<JSON

Add this to the "rewrites" array in the repo-root vercel.json (order before /p/:slug).
All three rules are needed: :path* does NOT match the bare trailing-slash form.

    { "source": "$BASE_PATH/:path*", "destination": "$url$BASE_PATH/:path*" },
    { "source": "$BASE_PATH/", "destination": "$url$BASE_PATH/" },
    { "source": "$BASE_PATH", "destination": "$url$BASE_PATH/" }

Then commit + let Vercel deploy: the console appears at https://settlepay.uk$BASE_PATH/
JSON
    ;;

  schedule)
    url="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
    sa="ops-tick@$PROJECT.iam.gserviceaccount.com"
    gcloud iam service-accounts describe "$sa" --project "$PROJECT" >/dev/null 2>&1 || \
      gcloud iam service-accounts create ops-tick --display-name "ops tick invoker" --project "$PROJECT"
    gcloud scheduler jobs describe ops-tick --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 && \
      gcloud scheduler jobs delete ops-tick --location "$REGION" --project "$PROJECT" --quiet
    # Matched to the send window (sequence_config send_window: Mon-Fri 08:00-15:00).
    # Ticks used to run 07:00-18:59, and because instance-based billing charges for
    # the whole instance lifecycle — and a tick every 10 minutes never lets it scale
    # to zero — that kept the container warm ~12h/day to do nothing outside the
    # window. 8-14 covers every slot (the last is ~14:43, one tick short of close).
    gcloud scheduler jobs create http ops-tick --location "$REGION" --project "$PROJECT" \
      --schedule "*/10 8-14 * * 1-5" --time-zone "Europe/London" \
      --uri "$url/tick" --http-method POST \
      --oidc-service-account-email "$sa" --oidc-token-audience "$url"
    echo "Scheduler created. Set on the service:"
    echo "  gcloud run services update $SERVICE --region $REGION --project $PROJECT \\"
    echo "    --update-env-vars TICK_INVOKER_SA=$sa,TICK_AUDIENCE=$url"
    ;;

  rollback)
    gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT" --limit 5
    prev="$(gcloud run revisions list --service "$SERVICE" --region "$REGION" --project "$PROJECT" \
      --format 'value(metadata.name)' --limit 2 | tail -1)"
    [ -n "$prev" ] || { echo "no previous revision"; exit 1; }
    gcloud run services update-traffic "$SERVICE" --region "$REGION" --project "$PROJECT" \
      --to-revisions "$prev=100"
    echo "traffic -> $prev"
    ;;

  *)
    grep '^#' "$0" | head -20
    exit 1
    ;;
esac
