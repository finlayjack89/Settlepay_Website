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
import json
import re
import statistics
from pathlib import Path

from . import audit, config, db
from .llm import LLMUnavailable, draft_provider

PLAYBOOK_PATH = config.PROJECT_ROOT / "prompts" / "draft_email.md"
# Craft guidance vendored from the `copywriting` skill (see copywriting/SOURCE.md).
# Prepended to the playbook: largest constant block FIRST so the prompt is prefix-
# cacheable the moment Vertex enables implicit caching for this model (a probe on
# 2026-07-19 measured cached=0 on gemini-3-flash-preview, so there is no discount
# today — the ordering costs nothing and starts paying automatically).
CRAFT_DIR = config.PROJECT_ROOT / "prompts" / "copywriting"
CRAFT_FILES = ("cold-email-uk.md", "anti-patterns.md")
MAX_WORDS = 125
SUBJECT_MAX_CHARS = 50
LINK_RE = re.compile(r"(https?://|www\.|!\[|\]\(|<img|<a\s|mailto:)", re.I)
# the playbook must declare a version so the mechanism refuses an unmarked/garbage file
VERSION_RE = re.compile(r"PLAYBOOK VERSION:\s*(\S+)", re.I)

# structured contract — one model call returns both fields, so the subject is written
# with the body in front of it rather than bolted on by a second call.
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
    "required": ["subject", "body"],
}


def _prompt_version() -> str:
    """Derived from the playbook's own version marker so bumping the file
    auto-stamps drafts (graduation metrics are windowed per prompt_version)."""
    try:
        m = VERSION_RE.search(PLAYBOOK_PATH.read_text())
        return f"playbook-{m.group(1)}" if m else "playbook-unversioned"
    except OSError:
        return "playbook-unversioned"


PROMPT_VERSION = _prompt_version()
# SettlePay must never claim its OWN authorisation (recipient names may contain
# "Ltd"/"Limited", so we do NOT guard on those — only on self-authorisation claims).
FORBIDDEN = ("fca authorised", "fca-authorised", "fca authorized",
             "pci compliant", "pci-compliant", "pci dss")


class EnvelopeViolation(Exception):
    def __init__(self, company_number, violations):
        self.company_number, self.violations = company_number, violations
        super().__init__(f"{company_number}: envelope violations: {violations}")


def _craft_modules() -> str:
    """The vendored copywriting guidance, concatenated. Missing files are fatal:
    silently drafting without the craft brief still produces plausible-looking
    email, so nothing would fail loudly — exactly the failure worth refusing."""
    parts = []
    for name in CRAFT_FILES:
        p = CRAFT_DIR / name
        try:
            parts.append(p.read_text())
        except OSError as e:
            raise RuntimeError(f"missing vendored craft module {p}: {e}") from e
    return "\n\n---\n\n".join(parts)


def load_playbook(path=None) -> str:
    p = Path(path) if path else PLAYBOOK_PATH
    text = p.read_text()
    if not VERSION_RE.search(text):
        raise RuntimeError(f"{p} has no 'PLAYBOOK VERSION:' marker — refusing an unversioned playbook")
    return f"{_craft_modules()}\n\n---\n\n{text}"


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


def check_subject(subject: str) -> list[str]:
    """Subject-line rules. HARD: v1.x generated no subject at all and every draft
    stored NULL, which send.py would have posted as an empty Subject header."""
    v: list[str] = []
    s = (subject or "").strip()
    if not s:
        return ["empty subject"]
    if len(s) > SUBJECT_MAX_CHARS:
        v.append(f"subject >{SUBJECT_MAX_CHARS} chars (truncates on mobile)")
    words = s.split()
    if not (2 <= len(words) <= 8):
        v.append(f"subject is {len(words)} words (want 3-7)")
    if re.match(r"^\s*(re|fwd|fw)\s*:", s, re.I):
        v.append("deceptive Re:/Fwd: prefix")
    letters = [c for c in s if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        v.append("ALL CAPS subject")
    if LINK_RE.search(s):
        v.append("link in subject")
    if "{" in s or "}" in s:
        v.append("unrendered merge tag")
    if any(ord(c) > 0x2100 for c in s):
        v.append("emoji/symbol in subject")
    return v


# A greeting line: "Hi Sarah," / "Hello," — anything else is treated as missing.
GREETING_RE = re.compile(r"^(hi|hello|good (morning|afternoon))\b[^\n]{0,40}[,:]?\s*\n", re.I)

# Openers and phrases the craft module names as instantly pattern-matched as bulk.
BANNED_PHRASES = (
    "i came across", "i came accross", "hope this finds you well",
    "hope you are well", "hope you're well", "just following up",
    "circling back", "just bumping", "touching base", "reaching out to you",
    "i wanted to reach out", "quick question for you",
)


def _sentences(text: str) -> list[str]:
    """Prose sentences only. The greeting and sign-off are fixed furniture — counting
    them would flatter the burstiness measure with lengths the model never chose."""
    body = re.split(r"\n\s*kind regards", text, flags=re.I)[0]
    body = GREETING_RE.sub("", body.lstrip(), count=1)
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip().split()) > 1]


SOFT_MAX_WORDS = 108   # the playbook asks for "under 110"; MAX_WORDS is the hard floor


def check_style(text: str) -> list[str]:
    """SOFT checks — craft, not compliance. A failure earns one corrective retry
    and is then recorded rather than discarding the lead: bad rhythm is worth a
    rewrite, not worth throwing away a qualified corporate prospect."""
    v: list[str] = []
    low = text.lower()
    words = len(text.split())
    if words > SOFT_MAX_WORDS:
        # without this the model drifts to the 125 hard cap and ignores the brief
        v.append(f"{words} words (tighten to under {SOFT_MAX_WORDS})")
    # a UK owner-manager reads a missing greeting as brusque; v2.3 and earlier
    # produced none at all because the playbook's shape list started at the opener
    if not GREETING_RE.match(text.lstrip()):
        v.append("no greeting line")
    for phrase in BANNED_PHRASES:
        if phrase in low:
            v.append(f"banned opener/filler: {phrase!r}")
    if text.count("—") > 2:
        v.append("em-dash pile-up")
    sents = _sentences(text)
    if len(sents) >= 4:
        lengths = [len(s.split()) for s in sents]
        mean = statistics.fmean(lengths)
        # burstiness: flat, even sentence length is the clearest machine-prose tell
        if mean and statistics.pstdev(lengths) / mean < 0.30:
            v.append("flat sentence rhythm (no burstiness)")
    return v


# --- anti-fingerprint rotation ---------------------------------------------
# Asking a model to "vary the copy" does not work: it converges on one phrasing
# and every draft ends up with the same middle paragraph. That is a persuasion
# failure AND a deliverability one (identical bodies = a bulk fingerprint), so
# the variation is imposed from outside instead — a framework and a value angle
# chosen per lead. Deterministic (sha256 of the company number, NOT hash(),
# which is salted per process) so a re-draft of the same lead is reproducible.
FRAMEWORKS = (
    ("PAS", "Name the felt pain, sharpen it in one line, then resolve it."),
    ("BAB", "Sketch how it works now, then how it could look, then the bridge."),
    ("why-now", "Tie the observation to why this is worth their attention now."),
)
ANGLES = (
    "getting paid sooner — less chasing, fewer excuses not to pay",
    "the admin: no manual matching of payments to invoices at week's end",
    "looking established at the point of payment — their brand, their domain",
)
# Opener SHAPE must rotate too. With one worked example in the playbook the model
# copies it verbatim: a 49-draft sample opened 43 times with the word "Saw". The
# first three words are the most visible part of a bulk fingerprint, so they are
# assigned rather than left to the model.
OPENERS = (
    'observation-led: start with what you can see they do ("Saw ...", "Noticed ...")',
    "reader-led: start with the word \"You\" or \"Your\" and their situation",
    'category-led: start from what firms in their trade typically do, then narrow to them',
    'causal: start with "Since ..." or "Because ..." tying their setup to the payment point',
    "name-led: start with the business's name and what it does, then the implication",
    'time-led: start from when the payment problem bites ("End of the month usually ...")',
)
SUBJECT_SHAPES = (
    "name the PAIN they feel, in their words, with no company name",
    "name the BUSINESS and the outcome they'd get",
    "name the MECHANISM plainly, with their trade rather than their name",
    "name the MOMENT it bites — the point in their week or month",
)  # deliberately no worked examples: an example here got copied into 16/49 subjects


def draft_angle(company_number: str) -> str:
    """A per-lead framework/emphasis/opener directive. Goes in the VARIABLE tail of
    the prompt, after the constant prefix, so it never breaks prefix caching."""
    import hashlib

    h = hashlib.sha256((company_number or "").encode()).digest()
    name, how = FRAMEWORKS[h[0] % len(FRAMEWORKS)]
    angle = ANGLES[h[1] % len(ANGLES)]
    opener = OPENERS[h[2] % len(OPENERS)]
    subject = SUBJECT_SHAPES[h[3] % len(SUBJECT_SHAPES)]
    return (f"STRUCTURE: use {name} for the body — {how}\n"
            f"EMPHASIS: lead the value on {angle}.\n"
            f"OPENER: {opener}. Follow it with the implication for how they get paid.\n"
            f"SUBJECT SHAPE: {subject}.\n"
            "These are assigned per lead so no two emails share an opening. Do NOT "
            "copy the worked example in the playbook — use its logic, not its words.\n")


class DraftFormatError(Exception):
    """The provider did not return the {subject, body} contract."""


def parse_payload(text: str) -> tuple[str, str]:
    """Parse the structured draft. Tolerates a fenced code block, which some
    providers wrap JSON in even when a schema is requested."""
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", raw, flags=re.I | re.S).strip()
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise DraftFormatError(f"not JSON: {raw[:120]!r}") from e
    if not isinstance(data, dict) or "subject" not in data or "body" not in data:
        raise DraftFormatError(f"missing subject/body keys: {sorted(data)[:6]}")
    return str(data["subject"]).strip(), str(data["body"]).strip()


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
        "Kind regards,\nFinlay Salisbury\nSettlePay"
    )


def provisional_responder(prompt: str) -> str:
    """Emits the {subject, body} contract so the provisional path exercises the
    same parse/validate route the real providers take."""
    company = _extract(prompt, "COMPANY:")
    return json.dumps({
        "subject": "provisional placeholder draft",
        "body": provisional_draft(company, _extract(prompt, "SIGNAL:")),
    })


# ---- the mechanism ----
def draft_one(company_number: str, company_name: str, signal: str, *,
              provider, cur, playbook: str | None = None,
              contact_name: str | None = None) -> dict:
    playbook = playbook or load_playbook()
    # per-lead variables LAST: everything above is a byte-identical prefix across
    # leads, which is what a prefix cache needs.
    prompt = (f"{playbook}\n\n{draft_angle(company_number)}"
              f"COMPANY: {company_name}\nSIGNAL: {signal or ''}\n")
    if contact_name:
        prompt += (f"CONTACT NAME: {contact_name}\n"
                   "Greet them by FIRST NAME only. Do not use their surname or any "
                   "title, and do not mention where you found their name.\n")

    def ask(extra: str = "") -> tuple[str, str]:
        r = provider.complete(prompt + extra, purpose="draft", max_words=MAX_WORDS,
                              schema=DRAFT_SCHEMA)
        return parse_payload(r.text)

    try:
        subject, body = ask()
    except DraftFormatError as e:
        try:
            subject, body = ask(f"\n\n---\nYour previous reply was not valid: {e}. "
                                'Return ONLY JSON: {"subject": "...", "body": "..."}')
        except DraftFormatError as e2:
            # must surface as EnvelopeViolation: that is the exception run()
            # isolates per-lead, and anything else aborts the whole batch.
            raise EnvelopeViolation(company_number, [f"unparseable draft: {e2}"]) from e2

    # HARD gates (compliance + a sendable subject) and SOFT gates (craft) share one
    # corrective retry; only the hard ones can discard the lead.
    hard = check_envelope(body) + [f"subject: {s}" for s in check_subject(subject)]
    soft = check_style(body)
    if hard or soft:
        try:
            r_subject, r_body = ask(
                f"\n\n---\nYour previous draft was rejected: {hard + soft}. "
                "Rewrite it in UNDER 110 words, keeping every required element: the "
                "'FCA-regulated partners' line, the reply-'unsubscribe' line, and the "
                "'Kind regards, / Finlay Salisbury / SettlePay' sign-off. No links. "
                "Vary sentence length. Give a 3-7 word lowercase subject under 50 "
                "characters.")
        except DraftFormatError as e:
            raise EnvelopeViolation(company_number, [f"unparseable retry: {e}"]) from e
        rv = check_envelope(r_body) + [f"subject: {s}" for s in check_subject(r_subject)]
        if rv:
            raise EnvelopeViolation(company_number, rv)
        subject, body, soft = r_subject, r_body, check_style(r_body)

    cur.execute(
        "insert into outreach.drafts (company_number, subject, body_original, "
        "prompt_version, status) values (%s, %s, %s, %s, 'awaiting_approval') returning id",
        (company_number, subject, body, PROMPT_VERSION),
    )
    draft_id = cur.fetchone()[0]
    cur.execute(
        "update outreach.leads set state='drafted', updated_at=now() "
        "where company_number=%s and state='enriched'", (company_number,))
    note = f"draft {draft_id} ({PROMPT_VERSION}); envelope ok"
    if soft:
        note += f"; style noted: {soft}"
    audit.record(company_number, "drafted", source="draft",
                 lawful_basis=audit.LEGITIMATE_INTERESTS, reason=note, cur=cur)
    return {"company_number": company_number, "draft_id": str(draft_id),
            "subject": subject, "words": len(body.split()),
            **({"style": soft} if soft else {})}


def run(*, provider=None, cur=None, limit=None) -> list[dict]:
    if provider is None:
        # api when configured (real unattended drafts); otherwise the safe
        # provisional fallback so a bare run never fabricates a real-looking email.
        provider = draft_provider(responder=provisional_responder)
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
            "where l.state='enriched' order by l.updated_at "
            + ("limit %s" if limit else ""), ((limit,) if limit else ())
        )
        for cn, name, sig in cur.fetchall():
            # Per-lead savepoint: one lead's failure must never discard the whole
            # batch (a single overlong draft used to roll back every good one).
            cur.execute("savepoint draft_lead")
            try:
                results.append(draft_one(cn, name, sig, provider=provider,
                                         cur=cur, playbook=playbook))
                cur.execute("release savepoint draft_lead")
            except EnvelopeViolation as e:
                # Unfixable after one retry — discard this lead (bounded: it will
                # not be re-drafted every tick) and keep going.
                cur.execute("rollback to savepoint draft_lead")
                cur.execute("update outreach.leads set state='discarded', "
                            "updated_at=now() where company_number=%s "
                            "and state='enriched'", (cn,))
                audit.record(cn, "draft_discarded", source="draft",
                             lawful_basis=audit.LEGITIMATE_INTERESTS,
                             reason=f"envelope unfixable after retry: {e.violations}",
                             cur=cur)
            except LLMUnavailable as e:
                # Brain down or spend cap hit — stop, but keep the good drafts.
                cur.execute("rollback to savepoint draft_lead")
                results.append({"halted": str(e)})
                break
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
