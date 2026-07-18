# Deploying the ops platform to Cloud Run (on-demand mode)

The console + pipeline ship as ONE container. Cloud Run runs it **on demand**:
`min-instances=0`, so the platform scales to zero when you're not using it
(idle cost ≈ £0, cold start ~5–10 s) and wakes when you open the dashboard.
Instance-based billing (`--no-cpu-throttling`) keeps the in-process JobRunner
executing launched jobs while the instance is warm. There is **no scheduler**
until you go live — you advance the pipeline from the console's **Launch** page.

## Account topology (deliberate split)

| Piece | Where | Why |
|---|---|---|
| Hosting (Cloud Run, Artifact Registry, Secret Manager) | Your **personal-account** GCP project | Billing/infra don't care about orgs |
| **Gmail OAuth client** | A tiny project under the **settlepay.uk Workspace org** | Only org projects get an **Internal** consent screen → durable refresh token. Personal = External = 7-day token expiry or Google verification |

The OAuth client's *values* (`GOOGLE_CLIENT_ID/SECRET`, minted `GOOGLE_REFRESH_TOKEN`)
are stored as secrets in the hosting project — tokens work anywhere.

## One-time setup (operator)

1. **OAuth client** — sign in to console.cloud.google.com as your `@settlepay.uk`
   Workspace admin → new project (e.g. `settlepay-oauth`) → *OAuth consent screen* →
   **Internal** → *Credentials* → **OAuth client ID → Desktop app**. Put the ID +
   secret in `outreach/.env`, then mint the token (sign in AS the sending mailbox):

       .venv/bin/python -m outreach auth-google      # -> GOOGLE_REFRESH_TOKEN

2. **Console password + session secret**:

       .venv/bin/python -m outreach hash-password    # -> CONSOLE_PASSWORD_HASH
       openssl rand -hex 32                          # -> SESSION_SECRET

3. **gcloud** on your Mac: `brew install google-cloud-sdk && gcloud auth login`
   (personal account), then:

       export GCLOUD_PROJECT=<your hosting project id>

## Deploy

    cd outreach
    ops/deploy-cloudrun.sh bootstrap        # APIs + registry + empty secrets
    ops/deploy-cloudrun.sh secret DATABASE_URL          # paste value, Ctrl-D
    ops/deploy-cloudrun.sh secret ANTHROPIC_API_KEY     # ... one per secret
    ops/deploy-cloudrun.sh build            # Cloud Build (no local docker needed)
    ops/deploy-cloudrun.sh deploy           # -> prints https://…run.app/dashboard/

Apply migrations from your Mac (same Supabase DB the service uses):

    .venv/bin/python -m outreach.migrate

## Wire settlepay.uk/dashboard

    ops/deploy-cloudrun.sh rewrite          # prints the exact vercel.json snippet

Paste it into the repo-root `vercel.json` `rewrites` array, commit, and Vercel
serves the console at **https://settlepay.uk/dashboard** (the `*.run.app` URL
keeps working too; both are behind the console login once secrets are set —
`CONSOLE_PASSWORD_HASH` + `SESSION_SECRET` unset would mean an OPEN console, so
they are in the required secrets list).

## Going live (later)

- DNS on the sending domain (SPF / DKIM / DMARC) → `dns_check` task shows READY.
- Re-set `INBOUND_SOURCE=gmail` once the both-scopes token is minted.
- `ops/deploy-cloudrun.sh schedule` — adds Cloud Scheduler → `POST /tick`
  (OIDC-verified) so warm-up volume is steady rather than bursty, and sets
  `TICK_INVOKER_SA`/`TICK_AUDIENCE` (command printed by the script).
- A human sets `G_SEND=1` via `gcloud run services update … --update-env-vars`.
  The platform can never set it.

## Rollback

    ops/deploy-cloudrun.sh rollback         # traffic -> previous revision

## Local always-on service (superseded)

`ops/install-console.sh` (the macOS launchd agent on :8787) predates the cloud
deploy. Keep it for pure-local use or remove it with `ops/uninstall-console.sh`
once the Cloud Run console is your daily surface.
