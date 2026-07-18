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

OPS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$(cd "$OPS_DIR/.." && pwd)"   # the outreach/ project dir (build context)

# Secret Manager names consumed by the service (values are set via `secret`).
SECRETS=(DATABASE_URL COMPANIES_HOUSE_API_KEY MILLIONVERIFIER_API_KEY
         FIRECRAWL_API_KEY ANTHROPIC_API_KEY GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
         GOOGLE_REFRESH_TOKEN CONSOLE_PASSWORD_HASH SESSION_SECRET)

# Non-secret runtime config. Deliberately conservative: autonomy off, inbound
# inline, dry-run posture. Flip via `gcloud run services update --update-env-vars`.
ENV_VARS="BASE_PATH=$BASE_PATH,DB_SCHEMA=outreach,ENQUIRY_SOURCE_TABLE=leads"
ENV_VARS+=",LLM_PROVIDER=api,WEBSITE_RESOLVER=firecrawl,INBOUND_SOURCE=inline"
ENV_VARS+=",PIPELINE_AUTONOMOUS=0,GMAIL_SENDER=${GMAIL_SENDER:-finlay@settlepaygroup.uk}"

cmd="${1:-}"

case "$cmd" in
  bootstrap)
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
      artifactregistry.googleapis.com secretmanager.googleapis.com \
      cloudscheduler.googleapis.com --project "$PROJECT"
    gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" \
      >/dev/null 2>&1 || gcloud artifacts repositories create "$REPO" \
      --repository-format docker --location "$REGION" --project "$PROJECT"
    for s in "${SECRETS[@]}"; do
      gcloud secrets describe "$s" --project "$PROJECT" >/dev/null 2>&1 || {
        echo "creating empty secret $s — set it with: ops/deploy-cloudrun.sh secret $s"
        printf 'CHANGE-ME' | gcloud secrets create "$s" --data-file=- --project "$PROJECT"
      }
    done
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
          --allow-unauthenticated       # app-level login guards the console
          --min-instances 0 --max-instances 1
          --no-cpu-throttling           # JobRunner keeps CPU while warm
          --memory 512Mi --cpu 1 --timeout 300
          --set-env-vars "$ENV_VARS")
    for s in "${SECRETS[@]}"; do
      args+=(--update-secrets "$s=$s:latest")
    done
    gcloud run deploy "$SERVICE" "${args[@]}"
    url="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
    echo ""
    echo "Deployed: $url$BASE_PATH/"
    echo "Next: ops/deploy-cloudrun.sh rewrite   # wire settlepay.uk/dashboard"
    ;;

  rewrite)
    url="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format 'value(status.url)')"
    cat <<JSON

Add this to the "rewrites" array in the repo-root vercel.json (order before /p/:slug):

    { "source": "$BASE_PATH/:path*", "destination": "$url$BASE_PATH/:path*" },
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
    gcloud scheduler jobs create http ops-tick --location "$REGION" --project "$PROJECT" \
      --schedule "*/10 7-18 * * 1-5" --time-zone "Europe/London" \
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
