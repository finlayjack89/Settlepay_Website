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

# --- budget caps (build-time) ---
CH_MAX_REQUESTS_PER_RUN = _int("CH_MAX_REQUESTS_PER_RUN", 50)
MV_MAX_PER_RUN = _int("MV_MAX_PER_RUN", 20)

# --- LLM provider ---
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "inline")

# --- live-send gate (human-only; the loop must NEVER set this) ---
G_SEND = os.environ.get("G_SEND")


def send_enabled() -> bool:
    """Live sending is enabled ONLY when a human has set G_SEND truthy. The loop
    can never flip this; absence/falsey == disabled (dry-run only)."""
    return str(G_SEND).strip().lower() in {"1", "true", "yes", "on"}
