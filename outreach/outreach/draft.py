"""Phase E — draft_email.

Loads the editable prompts/draft_email.md playbook (now v1 — real conversion copy),
asks the drafting provider to produce a draft into body_original, and enforces the
structural/compliance envelope before storing it.

Drafting provider:
- api (unattended): set LLM_PROVIDER=api (+ key) — the Anthropic API writes the draft.
- inline (attended): under /loop on Claude Max, the loop agent supplies the draft.
- provisional (safe default): with neither of the above, `provisional_responder`
  emits a clearly-marked, non-sending PROVISIONAL draft, so a bare run never
  fabricates a real-looking email without a real model behind it.
"""
from __future__ import annotations
import re
from pathlib import Path

from . import audit, config, db
from .llm import get_provider

PLAYBOOK_PATH = config.PROJECT_ROOT / "prompts" / "draft_email.md"
PROMPT_VERSION = "playbook-v1"
MAX_WORDS = 125
LINK_RE = re.compile(r"(https?://|www\.|!\[|\]\(|<img|<a\s|mailto:)", re.I)
# the playbook must declare a version so the mechanism refuses an unmarked/garbage file
VERSION_RE = re.compile(r"PLAYBOOK VERSION:\s*(\S+)", re.I)
# SettlePay must never claim its OWN authorisation (recipient names may contain
# "Ltd"/"Limited", so we do NOT guard on those — only on self-authorisation claims).
FORBIDDEN = ("fca authorised", "fca-authorised", "fca authorized",
             "pci compliant", "pci-compliant", "pci dss")


class EnvelopeViolation(Exception):
    def __init__(self, company_number, violations):
        self.company_number, self.violations = company_number, violations
        super().__init__(f"{company_number}: envelope violations: {violations}")


def load_playbook(path=None) -> str:
    p = Path(path) if path else PLAYBOOK_PATH
    text = p.read_text()
    if not VERSION_RE.search(text):
        raise RuntimeError(f"{p} has no 'PLAYBOOK VERSION:' marker — refusing an unversioned playbook")
    return text


def check_envelope(text: str) -> list[str]:
    """Structural/compliance checks (mirrors the floor). Empty list == compliant."""
    v: list[str] = []
    low = text.lower()
    if len(text.split()) >= MAX_WORDS:
        v.append(f">={MAX_WORDS} words")
    if "unsubscribe" not in low:
        v.append("no unsubscribe line")
    if "settlepay" not in low:
        v.append("no SettlePay sender id")
    if "fca-regulated partner" not in low:
        v.append("missing 'FCA-regulated partners'")
    if LINK_RE.search(text):
        v.append("contains a link/image")
    for bad in FORBIDDEN:
        if bad in low:
            v.append(f"forbidden self-claim: {bad!r}")
    return v


# ---- the inline build responder: a clearly-marked PROVISIONAL placeholder ----
def _extract(prompt: str, key: str) -> str:
    for line in prompt.splitlines():
        if line.startswith(key):
            return line[len(key):].strip()
    return ""


def provisional_draft(company_name: str, signal: str) -> str:
    """A minimal, compliant, explicitly-provisional message — NOT conversion copy.
    The researched playbook replaces this; it exists only to exercise the mechanism."""
    company = (company_name or "there").strip()
    sig = " ".join((signal or "").split()[:25])
    return (
        f"Hello {company},\n\n"
        "This is a PROVISIONAL PLACEHOLDER, generated only to exercise SettlePay's "
        "drafting mechanism. The approved messaging is not written yet, so it is not "
        "for sending.\n\n"
        f"Context on file: {sig}\n\n"
        "Any payment processing would be handled by FCA-regulated partners, not by "
        "SettlePay directly.\n\n"
        "To opt out of future messages, reply with the word unsubscribe.\n\n"
        "Finlay Salisbury, trading as SettlePay"
    )


def provisional_responder(prompt: str) -> str:
    return provisional_draft(_extract(prompt, "COMPANY:"), _extract(prompt, "SIGNAL:"))


# ---- the mechanism ----
def draft_one(company_number: str, company_name: str, signal: str, *,
              provider, cur, playbook: str | None = None) -> dict:
    playbook = playbook or load_playbook()
    prompt = f"{playbook}\n\nCOMPANY: {company_name}\nSIGNAL: {signal or ''}\n"
    body = provider.complete(prompt, purpose="draft", max_words=MAX_WORDS).text.strip()

    violations = check_envelope(body)
    if violations:
        raise EnvelopeViolation(company_number, violations)

    cur.execute(
        "insert into outreach.drafts (company_number, body_original, prompt_version, status) "
        "values (%s, %s, %s, 'awaiting_approval') returning id",
        (company_number, body, PROMPT_VERSION),
    )
    draft_id = cur.fetchone()[0]
    cur.execute(
        "update outreach.leads set state='drafted', updated_at=now() "
        "where company_number=%s and state='enriched'", (company_number,))
    audit.record(company_number, "drafted", source="draft",
                 lawful_basis=audit.LEGITIMATE_INTERESTS,
                 reason=f"draft {draft_id} ({PROMPT_VERSION}); envelope ok", cur=cur)
    return {"company_number": company_number, "draft_id": str(draft_id), "words": len(body.split())}


def run(*, provider=None, cur=None) -> list[dict]:
    if provider is None:
        # api when configured (real unattended drafts); otherwise the safe
        # provisional fallback so a bare run never fabricates a real-looking email.
        provider = (get_provider("api") if config.LLM_PROVIDER == "api"
                    else get_provider("inline", responder=provisional_responder))
    own = cur is None
    conn = None
    if own:
        conn = db.connect()
        cur = conn.cursor()
    playbook = load_playbook()
    results: list[dict] = []
    try:
        cur.execute(
            "select l.company_number, l.company_name, e.signal from outreach.leads l "
            "join outreach.enrichment e on e.company_number=l.company_number "
            "where l.state='enriched'"
        )
        for cn, name, sig in cur.fetchall():
            results.append(draft_one(cn, name, sig, provider=provider, cur=cur, playbook=playbook))
        if own:
            conn.commit()
        return results
    except Exception:
        if own and conn is not None:
            conn.rollback()
        raise
    finally:
        if own and conn is not None:
            conn.close()


if __name__ == "__main__":
    print(run())
