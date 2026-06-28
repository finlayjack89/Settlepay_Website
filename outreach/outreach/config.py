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

# --- LLM provider ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "inline")

# --- send: Microsoft Graph (phase G), from a SEPARATE warmed domain (never @settlepay.uk) ---
GRAPH_TENANT_ID = os.environ.get("GRAPH_TENANT_ID")
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET")
GRAPH_SENDER = os.environ.get("GRAPH_SENDER")

# --- send guardrails (phase G) ---
PER_INBOX_DAILY_CAP = _int("PER_INBOX_DAILY_CAP", 5)
KILL_SWITCH = os.environ.get("KILL_SWITCH")  # truthy => block ALL sends (dry-run included)

# --- live-send gate (human-only; the loop must NEVER set this) ---
G_SEND = os.environ.get("G_SEND")


def send_enabled() -> bool:
    """Live sending is enabled ONLY when a human has set G_SEND truthy. The loop
    can never flip this; absence/falsey == disabled (dry-run only)."""
    return str(G_SEND).strip().lower() in {"1", "true", "yes", "on"}
