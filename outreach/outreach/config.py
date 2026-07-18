"""Runtime configuration, loaded from outreach/.env. Secrets live ONLY in .env."""
from __future__ import annotations
import os
import pathlib

from dotenv import load_dotenv

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# --- connection / schema ---
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_SCHEMA = os.environ.get("DB_SCHEMA", "outreach")
# website inbound-enquiry source (public schema) to suppress against
ENQUIRY_SOURCE_TABLE = os.environ.get("ENQUIRY_SOURCE_TABLE", "leads")

# --- external APIs ---
COMPANIES_HOUSE_API_KEY = os.environ.get("COMPANIES_HOUSE_API_KEY")
MILLIONVERIFIER_API_KEY = os.environ.get("MILLIONVERIFIER_API_KEY")

# --- website discovery (phase D): inline (loop agent) | firecrawl | brave ---
WEBSITE_RESOLVER = os.environ.get("WEBSITE_RESOLVER", "inline")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY")
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY")

# --- budget caps (build-time) ---
CH_MAX_REQUESTS_PER_RUN = _int("CH_MAX_REQUESTS_PER_RUN", 50)
MV_MAX_PER_RUN = _int("MV_MAX_PER_RUN", 20)
SEARCH_MAX_REQUESTS_PER_RUN = _int("SEARCH_MAX_REQUESTS_PER_RUN", 50)

# --- contact verification tiers ---
# Catch-all mailboxes (MillionVerifier 'catch_all') are deliverable but unconfirmable.
# Accept them into a 'risky' tier (default on) rather than discarding reachable
# businesses; sending to them needs a SEPARATE opt-in beyond G-SEND.
ACCEPT_CATCH_ALL = _bool("ACCEPT_CATCH_ALL", True)
RISKY_SEND_ENABLED = _bool("RISKY_SEND_ENABLED", False)

# --- LLM provider ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "inline")
# api provider (the unattended "brain" — lets enrich/draft run with no human loop
# session, which is what makes headless/cloud operation possible).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
# verified against ~/.claude/LLM_MODELS.md — do not "correct" from memory. Override via env.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# --- autonomy (unattended, scheduled operation) ---
# Master gate for the FULL-CHAIN tick (discover -> enrich -> draft). Off by default:
# a bare tick stays the safe classify+send only. Turn on for headless operation.
PIPELINE_AUTONOMOUS = _bool("PIPELINE_AUTONOMOUS", False)
DISCOVER_PER_TICK = _int("DISCOVER_PER_TICK", 10)
ENRICH_PER_TICK = _int("ENRICH_PER_TICK", 10)
DRAFT_PER_TICK = _int("DRAFT_PER_TICK", 10)
FOLLOWUP_PER_TICK = _int("FOLLOWUP_PER_TICK", 10)
INBOUND_MAX_PER_RUN = _int("INBOUND_MAX_PER_RUN", 50)
# CSV of SIC codes to discover; empty => targeting.TARGET_SICS (the ICP default set).
TARGET_SIC_CODES = os.environ.get("TARGET_SIC_CODES", "")
# per-vertical graduation auto-approve (lights-out). Off until a vertical proves out.
AUTO_APPROVE_ENABLED = _bool("AUTO_APPROVE_ENABLED", False)

# --- spend ceiling (hard stop across paid providers: MillionVerifier + Anthropic) ---
def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MONTHLY_SPEND_CAP_GBP = _float("MONTHLY_SPEND_CAP_GBP", 50.0)
# token -> GBP conversion for the spend ledger (claude-sonnet-4-6 list prices; override on model change)
ANTHROPIC_INPUT_USD_PER_MTOK = _float("ANTHROPIC_INPUT_USD_PER_MTOK", 3.0)
ANTHROPIC_OUTPUT_USD_PER_MTOK = _float("ANTHROPIC_OUTPUT_USD_PER_MTOK", 15.0)
USD_TO_GBP = _float("USD_TO_GBP", 0.79)
MV_COST_GBP_PER_VERIFY = _float("MV_COST_GBP_PER_VERIFY", 0.003)
# max chars of scraped page text fed to the LLM signal prompt
ENRICH_PAGE_TEXT_MAX_CHARS = _int("ENRICH_PAGE_TEXT_MAX_CHARS", 6000)

# --- operator alerting / digests (transactional mail to the operator, not outreach) ---
OPERATOR_EMAIL = os.environ.get("OPERATOR_EMAIL")

# --- console (web) ---
# Path prefix when proxied at settlepay.uk/dashboard via a Vercel rewrite ("" locally).
BASE_PATH = os.environ.get("BASE_PATH", "").rstrip("/")
# argon2id hash minted by `python -m outreach hash-password`; unset => console refuses login.
CONSOLE_PASSWORD_HASH = os.environ.get("CONSOLE_PASSWORD_HASH")
SESSION_SECRET = os.environ.get("SESSION_SECRET")  # signs session cookies; never commit/log
SESSION_TTL_HOURS = _int("SESSION_TTL_HOURS", 12)
# Cloud Scheduler OIDC: the service-account email allowed to invoke POST /tick.
TICK_INVOKER_SA = os.environ.get("TICK_INVOKER_SA")
TICK_AUDIENCE = os.environ.get("TICK_AUDIENCE")  # the Cloud Run service URL

# --- inbound ingestion (reply/bounce/unsubscribe): inline (default) | gmail (TODO) ---
# Mailboxes moved to Google Workspace; the Graph reader is retired. Reading replies via
# Gmail (needs a broader gmail.readonly scope + its own consent) is a tracked follow-up.
INBOUND_SOURCE = os.environ.get("INBOUND_SOURCE", "inline")

# --- send: Gmail API (phase G), per-user OAuth from a SEPARATE Google Workspace
# secondary domain (never @settlepay.uk). The refresh token is mailbox-scoped, so it
# can only ever send as the one mailbox that consented (no domain-wide delegation). ---
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN")  # durable; .env only, never commit/log
GMAIL_SENDER = os.environ.get("GMAIL_SENDER")                  # e.g. finlay@getsettlepay.uk

# --- send guardrails (phase G) ---
# Google Workspace tolerates a higher cold limit (~18-22/inbox/day) than M365 (3-5);
# keep the default conservative — raise via env, no code change needed.
PER_INBOX_DAILY_CAP = _int("PER_INBOX_DAILY_CAP", 5)
KILL_SWITCH = os.environ.get("KILL_SWITCH")  # truthy => block ALL sends (dry-run included)

# --- live-send gate (human-only; the loop must NEVER set this) ---
G_SEND = os.environ.get("G_SEND")


def send_enabled() -> bool:
    """Live sending is enabled ONLY when a human has set G_SEND truthy. The loop
    can never flip this; absence/falsey == disabled (dry-run only)."""
    return str(G_SEND).strip().lower() in {"1", "true", "yes", "on"}
