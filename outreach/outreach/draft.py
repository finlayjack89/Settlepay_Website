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

from . import audit, config, db, facts, states
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


# A greeting line, always "Dear <business name or first name>," on its own line.
# Anything else (a bare "Hi,", no greeting, a company shouted in capitals with "Ltd")
# is treated as missing so the soft check catches it.
GREETING_RE = re.compile(r"^dear\s+[^\n]{1,60}[,:]\s*\n", re.I)

# Any opener that addresses someone by a first name: "Dear John,", "Hi Robert,",
# "Hello Sarah -". The captured token is the name the draft is greeting.
_GREET_NAME_RE = re.compile(r"^\s*(?:dear|hi|hello|hey)\s+([A-Z][a-z]+)\b", re.I)
_STOPWORD_GREETS = frozenset({"there", "team", "sir", "madam", "all", "sirs", "everyone"})


def _grounding_tokens(*sources: str | None) -> set[str]:
    """Lowercased words we are allowed to greet by — the verified contact's forename
    and every word of the business's own name."""
    out: set[str] = set()
    for s in sources:
        for w in re.split(r"[^a-z0-9]+", (s or "").lower()):
            if len(w) >= 2:
                out.add(w)
    return out


# A place claim: a preposition followed by a proper noun ("in Macclesfield", "across
# Greater Manchester"). This is where a location assertion actually lands in a sentence,
# which makes it checkable without a gazetteer or a NER model.
_PROPER_NOUN = r"[A-Z][a-z’']+(?:-[A-Z][a-z’']+)*"      # Hull, Westbury-On-Severn
# Prepositions that unambiguously introduce a LOCATION. Bare "in" is deliberately not
# here: it produced the false positives that made this gate destroy good leads — "in
# Xero", "in January", "in Sterling", "in Victorian terraces" were all read as place
# claims, each one a hard reject. Bare "in" is still caught, but only via the gazetteer
# below, where the phrase is a town we can actually recognise.
_PLACE_CLAIM_RE = re.compile(
    r"\b(?:based\s+in|here\s+in|over\s+in|out\s+of|across|around|near|throughout|"
    r"serving|covering)\s+"
    rf"({_PROPER_NOUN}(?:\s+{_PROPER_NOUN}){{0,2}})")   # + Greater Manchester
# The softer trigger. "in Macclesfield" is a place claim; "in Xero" is not — and the
# only reliable way to tell them apart without a NER model is to recognise the town.
_SOFT_PLACE_RE = re.compile(rf"\bin\s+({_PROPER_NOUN}(?:\s+{_PROPER_NOUN}){{0,2}})")

# Geographies that assert nothing specific about this lead, plus the words a capitalised
# run can legitimately start with mid-sentence.
_GENERIC_PLACES = frozenset({
    "the uk", "uk", "the united kingdom", "united kingdom", "britain", "great britain",
    "england", "scotland", "wales", "northern ireland", "the country", "the county",
    "the region", "the area", "your area", "the industry", "the trade",
})

# An unverifiable number about the recipient: a review score, a star rating, a count of
# customers. The one that reached production was "Your 9.9 rating on Checkatrade".
_STAT_CLAIM_RE = re.compile(
    r"\b\d[\d,.]*\s*(?:\+|%)?\s*"
    r"(?:[a-z]+[- ])?"                      # "500 five-star reviews", "4.9 average rating"
    r"(?:star|stars|rating|ratings|review|reviews|out of|/\s*5|/\s*10|years|customers|"
    r"clients|jobs|installs|projects)\b", re.I)

# How the RECIPIENT currently takes money. The playbook's whole "gap" paragraph invites
# this claim, and 107 of 137 queued drafts made it — while `payment_method` was a
# resolved fact on 0 of 460 enrichment rows. The facts block said
# "payment_method: UNKNOWN — do not state one", the playbook said "the gap is bank
# transfer / manual invoicing", and nothing deterministic adjudicated between them.
#
# Deliberately narrow: only nouns that name a payment MECHANISM. SettlePay's own offer
# ("a branded card-payment page", "they keep their bank") must not trip it, so there is
# no bare "card" or "bank" here — and "cash flow" is excluded explicitly.
_PAYMENT_CLAIM_RE = re.compile(
    r"\b(?:bank\s+transfers?|bacs|chaps|faster\s+payments?|sort\s*code|"
    r"standing\s+order|direct\s+debit|cheques?|"
    r"cash\b(?!\s*(?:flow|flow[- ]positive))|"
    r"manual(?:ly)?\s+invoic\w*|invoic\w+\s+(?:after|by\s+hand)|"
    r"card\s+machine|chip\s+and\s+pin|card\s+terminal|paper\s+invoice)\b", re.I)


_UK_PLACE_SUFFIXES = ("shire", "ton", "ford", "field", "bury", "borough", "burgh",
                      "mouth", "port", "bridge", "wich", "ham", "combe", "dale",
                      "pool", "cester", "chester", "minster", "stead", "wood")


def _looks_like_a_uk_place(phrase: str) -> bool:
    """Is this phrase recognisably a UK place, rather than a product, a month or a
    currency? Used only after a bare "in", where the preposition proves nothing.

    Two signals: the town gazetteer this project already ships for Places discovery,
    and the suffixes English place names are built from. Anything else is left alone —
    a false NEGATIVE here costs a missed hallucination that the location constant would
    usually have caught anyway, while a false POSITIVE used to cost the whole lead.
    """
    from . import targeting

    lowered = phrase.lower()
    towns = {t.lower() for t in targeting.PLACES_TOWNS}
    if lowered in towns or any(w in towns for w in lowered.split()):
        return True
    # Any SEGMENT may carry the place-name suffix, not just the last word:
    # "Westbury-On-Severn" is a place because of "Westbury", and checking only the tail
    # ("severn") missed it. The length floor keeps short words like "Wood" from firing.
    return any(len(part) > 5 and part.endswith(_UK_PLACE_SUFFIXES)
               for part in re.split(r"[^a-z]+", lowered) if part)


def check_grounding(text: str, *, contact_name: str | None,
                    company_name: str | None,
                    lead_facts: dict | None = None) -> list[str]:
    """HARD anti-hallucination gate: a draft may only name things we resolved.

    The playbook already forbids inventing a name or a place, yet the model still opened
    "Hi John," on a lead with no contact on file and placed businesses in towns nobody
    had verified — an instruction an LLM will occasionally ignore, so it cannot be the
    only line of defence. Three deterministic checks, each pinned to a real production
    failure:

      * a greeting naming a person who is neither the verified contact nor the business
      * a place claim naming somewhere that is not the resolved `location` constant
      * a statistic about the recipient (a rating, a review count) — always unverifiable

    A fabricated specific is worse than a general opener: it is both a lie and instantly
    detectable by the one person who would know.
    """
    allowed = (facts.allowed_tokens(lead_facts) if lead_facts
               else _grounding_tokens(first_name(contact_name), company_name))
    v: list[str] = []

    greeted = _GREET_NAME_RE.match(text.lstrip())
    if greeted:
        token = greeted.group(1).lower()
        known = first_name(facts.value(lead_facts, "contact_name") or contact_name)
        if token not in allowed and token not in _STOPWORD_GREETS:
            who = "an invented name" if not known else f"{token!r}, not the contact ({known!r})"
            v.append(f"greeting names {who}")

    body = GREETING_RE.sub("", text.lstrip(), count=1)   # the greeting is checked above
    seen_places: set[str] = set()
    for match in list(_PLACE_CLAIM_RE.finditer(body)) + list(_SOFT_PLACE_RE.finditer(body)):
        phrase = " ".join(match.group(1).split())
        if phrase.lower() in _GENERIC_PLACES or phrase in seen_places:
            continue
        # every word of the claimed place must be a resolved constant; "Greater
        # Manchester" passes only if the location constant actually says so
        if all(w in allowed for w in re.split(r"[^a-z0-9]+", phrase.lower()) if w):
            continue
        # After a bare "in", flag only what we can RECOGNISE as a UK place. Treating
        # every capitalised word as a place claim rejected "in Xero", "in January" and
        # "in Sterling" — and an unfixable violation used to discard the lead outright.
        if match.re is _SOFT_PLACE_RE and not _looks_like_a_uk_place(phrase):
            continue
        seen_places.add(phrase)
        v.append(f"names a place we did not verify: {phrase!r}")

    stat = _STAT_CLAIM_RE.search(body)
    if stat:
        v.append(f"unverifiable statistic about the recipient: {stat.group(0).strip()!r}")

    # The missing fourth check. A draft may say how the recipient gets paid only when
    # `payment_method` is a RESOLVED constant — which today means an auctioneer whose own
    # site quotes it. Everywhere else it is an inference presented as an observation
    # about their business, and it is the claim most likely to be flatly wrong to the one
    # person who would know.
    known_pay = facts.value(lead_facts, "payment_method") if lead_facts else None
    pay = _PAYMENT_CLAIM_RE.search(body)
    if pay and not (known_pay and pay.group(0).lower() in known_pay.lower()):
        claim = pay.group(0).strip()
        v.append(f"states how they take payment ({claim!r}) — "
                 + (f"the verified method is {known_pay!r}" if known_pay
                    else "payment_method is not a resolved fact for this lead"))
    return v


def first_name(contact_name: str | None) -> str | None:
    """The first name to greet a named contact by. Companies House holds names
    surname-first ('SMITH, John Andrew'); a scraped/manual name is 'John Smith'. Both
    reduce to 'John'. Returns None when there is no usable forename."""
    if not contact_name or not contact_name.strip():
        return None
    n = contact_name.strip()
    part = n.split(",", 1)[1] if "," in n else n     # after the comma = the forenames
    tokens = [t for t in part.split() if t]
    return tokens[0].title() if tokens else None


_SUFFIX_RE = re.compile(
    r"[\s,]+(ltd|limited|llp|plc|l\.?l\.?p\.?|"
    r"cyf|ccc|company|co)\.?$", re.I)


def _clean_business_name(company_name: str | None) -> str:
    """A business name fit to greet: the registered suffix dropped, and a SHOUTED
    all-caps name given ordinary capitalisation ('ACME JOINERY LTD' -> 'Acme Joinery').
    Used for the provisional fallback; the real drafter asks the model to do the same so
    the tidy reads naturally rather than mechanically."""
    name = (company_name or "there").strip()
    prev = None
    while prev != name:                               # strip stacked suffixes ("... Co Ltd")
        prev = name
        name = _SUFFIX_RE.sub("", name).strip()
    if name and name == name.upper():                 # all-caps -> Title Case, but keep
        # short initialisms shouting ('DC', 'JCB') rather than mangling them to 'Dc'
        name = " ".join(w if len(w) <= 2 else w.title() for w in name.split())
    return name or "there"

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
    # every draft opens "Dear <business name or first name>,"; a UK owner-manager reads
    # a missing or clumsy greeting as brusque
    if not GREETING_RE.match(text.lstrip()):
        v.append("no 'Dear <name>,' greeting line")
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
    company = _clean_business_name(company_name)
    sig = " ".join((signal or "").split()[:25])
    return (
        f"Dear {company},\n\n"
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
              contact_name: str | None = None,
              lead_facts: dict | None = None) -> dict:
    playbook = playbook or load_playbook()
    # Resolved constants are the drafter's ONLY vocabulary of named things. Falling back
    # to a block built from the arguments keeps every call path (tests, the manual
    # console re-draft, the batch) on the same contract.
    block = lead_facts if lead_facts is not None else facts.build(
        company_name=company_name, contact_name=contact_name,
        contact_name_source="enrichment" if contact_name else None)
    greet = first_name(facts.value(block, "contact_name") or contact_name)

    # per-lead variables LAST: everything above is a byte-identical prefix across
    # leads, which is what a prefix cache needs.
    prompt = (f"{playbook}\n\n{draft_angle(company_number)}"
              f"{facts.as_prompt_block(block)}\n"
              f"SIGNAL (context only — never a source of names or places): {signal or ''}\n")
    if greet:
        prompt += (f'Open with "Dear {greet}," on its own line. Use this first name '
                   "only — no surname, no title — and do not mention where you found "
                   "their name.\n")

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

    # HARD gates (compliance + a sendable subject + no invented person) and SOFT gates
    # (craft) share one corrective retry; only the hard ones can discard the lead.
    hard = (check_envelope(body)
            + [f"subject: {s}" for s in check_subject(subject)]
            + check_grounding(body, contact_name=contact_name, company_name=company_name,
                              lead_facts=block))
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
        rv = (check_envelope(r_body) + [f"subject: {s}" for s in check_subject(r_subject)]
              + check_grounding(r_body, contact_name=contact_name,
                                company_name=company_name, lead_facts=block))
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
        # 'parked' included so a lead we previously failed to write for rejoins cleanly,
        # and its park marks are cleared with it
        "update outreach.leads set state='drafted', updated_at=now(), "
        "  parked_reason=null, parked_at=null "
        "where company_number=%s and state in ('enriched','parked')", (company_number,))
    # the constants (and where each came from) are part of the record: if a draft is ever
    # challenged, this is what it was allowed to assert and why.
    note = f"draft {draft_id} ({PROMPT_VERSION}); envelope ok; facts {facts.summarise(block)}"
    if soft:
        note += f"; style noted: {soft}"
    audit.record(company_number, "drafted", source="draft",
                 lawful_basis=audit.LEGITIMATE_INTERESTS, reason=note, cur=cur)
    return {"company_number": company_number, "draft_id": str(draft_id),
            "subject": subject, "words": len(body.split()),
            **({"style": soft} if soft else {})}


def redraft_stale(*, limit: int = 25, cur=None, provider=None,
                  keep_version: str | None = None) -> dict:
    """Send drafts written by an older playbook back through the drafter.

    Only ever touches drafts still AWAITING APPROVAL: an approved or sent draft is a
    decision (or a record of one) and re-writing it would rewrite history. The old row is
    superseded rather than deleted, so what was previously in the queue stays auditable.

    Everything the current pipeline enforces — the constants, the grounding gate, the
    envelope — applies on the way through, because this is the ordinary drafting path
    with a different backlog query.
    """
    keep_version = keep_version or PROMPT_VERSION
    own = cur is None
    conn = None
    if own:
        conn = db.connect(); cur = conn.cursor()
    playbook = load_playbook()
    redrawn, skipped, failed = 0, 0, 0
    try:
        cur.execute(
            "select d.id, d.company_number, l.company_name, e.signal, e.contact_name, e.facts "
            "from outreach.drafts d "
            "join outreach.leads l on l.company_number = d.company_number "
            "join outreach.enrichment e on e.company_number = d.company_number "
            "where d.status = 'awaiting_approval' and d.prompt_version is distinct from %s "
            "  and e.facts is not null "
            "order by d.created_at limit %s", (keep_version, limit))
        for draft_id, cn, name, sig, contact_name, raw_facts in cur.fetchall():
            cur.execute("savepoint redraft_lead")
            try:
                block = facts.loads(raw_facts)
                if not facts.is_draftable(block):
                    skipped += 1
                    cur.execute("release savepoint redraft_lead")
                    continue
                # supersede first: the drafts table has no per-lead uniqueness, so the
                # old row would otherwise sit in the queue alongside its replacement
                cur.execute("update outreach.drafts set status='superseded' where id=%s",
                            (draft_id,))
                cur.execute("update outreach.leads set state='enriched' "
                            "where company_number=%s and state='drafted'", (cn,))
                draft_one(cn, name, sig, provider=provider or draft_provider(
                    responder=provisional_responder), cur=cur, playbook=playbook,
                    contact_name=contact_name, lead_facts=block)
                redrawn += 1
                cur.execute("release savepoint redraft_lead")
            except EnvelopeViolation as e:
                # the replacement failed its gates — leave the ORIGINAL in the queue
                # rather than emptying it, and record why
                cur.execute("rollback to savepoint redraft_lead")
                cur.execute("release savepoint redraft_lead")
                failed += 1
                audit.record(cn, "redraft_failed", source="draft",
                             lawful_basis=audit.LEGITIMATE_INTERESTS,
                             reason=f"kept the older draft: {e.violations}"[:400], cur=cur)
        if own:
            conn.commit()
    except Exception:
        if own and conn:
            conn.rollback()
        raise
    finally:
        if own and conn:
            conn.close()
    return {"redrafted": redrawn, "skipped_unresolved": skipped, "failed_kept_old": failed}


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
            # facts is not null == the constants have been RESOLVED. A lead enriched
            # before that step existed is not draftable on free text alone — it waits for
            # re-enrichment rather than being written about from a signal paragraph.
            "select l.company_number, l.company_name, e.signal, e.contact_name, e.facts "
            "from outreach.leads l "
            "join outreach.enrichment e on e.company_number=l.company_number "
            # Leads parked BY DRAFTING come back here rather than to enrichment: their
            # contact and constants are already good, it was our writing that failed, so
            # re-verifying them would spend credits to re-learn what we know. Leads
            # parked by enrichment carry a different reason and are not picked up here.
            # A catch-all ('risky') contact is refused at send unless RISKY_SEND_ENABLED,
            # so drafting one spends LLM credit and a slot of human review on an email
            # that cannot go out. It stays enriched and waits for that decision instead.
            "where e.facts is not null "
            "  and (%s or e.contact_tier is distinct from 'risky') "
            "  and (l.state='enriched' "
            "       or (l.state='parked' and l.parked_reason like 'draft %%' "
            "           and l.parked_at < now() - make_interval(hours => %s))) "
            "order by l.updated_at "
            + ("limit %s" if limit else ""),
            ((config.RISKY_SEND_ENABLED, config.PARK_RETRY_HOURS, limit) if limit
             else (config.RISKY_SEND_ENABLED, config.PARK_RETRY_HOURS))
        )
        for cn, name, sig, contact_name, raw_facts in cur.fetchall():
            # Per-lead savepoint: one lead's failure must never discard the whole
            # batch (a single overlong draft used to roll back every good one).
            cur.execute("savepoint draft_lead")
            try:
                block = facts.loads(raw_facts)
                if not facts.is_draftable(block):
                    cur.execute("release savepoint draft_lead")
                    continue          # constants incomplete: enrichment's job, not ours
                results.append(draft_one(cn, name, sig, provider=provider, cur=cur,
                                         playbook=playbook, contact_name=contact_name,
                                         lead_facts=block))
                cur.execute("release savepoint draft_lead")
            except EnvelopeViolation as e:
                # Unfixable after one retry — PARK, don't discard. This is our writing
                # failing, not a verdict about the lead: three of the five real discards
                # on this database were a subject line 51 characters long, and one more
                # was a draft one word over the limit. `discarded` is terminal, so each
                # of those destroyed an enriched, verified, ICP-fit lead we had already
                # paid to find. Parking still stops the lead being re-drafted every tick
                # (the backlog reads state='enriched') while leaving it recoverable once
                # the playbook or the envelope check is fixed.
                cur.execute("rollback to savepoint draft_lead")
                outcome = states.park_lead(cur, cn, f"draft envelope: {e.violations}")
                audit.record(cn, "parked" if outcome == "parked" else "draft_discarded",
                             source="draft", lawful_basis=audit.LEGITIMATE_INTERESTS,
                             reason=(f"envelope unfixable after retry: {e.violations}"
                                     + ("" if outcome == "parked"
                                        else f" — discarded after {states.PARK_MAX} attempts")),
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


# --------------------------------------------------------------------------- #
#  copy similarity — the thing nothing measured
# --------------------------------------------------------------------------- #
def _shingles(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {tuple(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def similarity_report(bodies: list[str], *, n: int = 4, threshold: float = 0.45) -> dict:
    """Pairwise n-gram Jaccard across a set of drafts.

    `draft_angle` rotates the INPUT and nothing ever checked the output, so the only
    evidence copy was diverging was that it looked different. It was not always: the
    v2.8 batch measured MORE homogeneous than the v2.4 batch it replaced (word-level
    mean 0.460 vs 0.399), which nobody could have known.

    Jaccard over 4-word shingles rather than difflib: SequenceMatcher's autojunk
    silently deflates the ratio on strings this long, which is why two earlier readings
    of the same corpus disagreed by a factor of three.

    The mandated tail (sign-off, the FCA line, the opt-out sentence) is shared by every
    compliant draft by construction, so `threshold` is about the PITCH, not the boiler-
    plate. Report, don't reject — this is a signal for the operator and for tuning the
    angle rotation, not another gate that can destroy a lead.
    """
    bodies = [b for b in bodies if b and b.strip()]
    if len(bodies) < 2:
        return {"pairs": 0, "mean": 0.0, "max": 0.0, "over_threshold": 0,
                "threshold": threshold, "worst": []}
    grams = [_shingles(b, n) for b in bodies]
    scores: list[tuple[float, int, int]] = []
    for i in range(len(grams)):
        for j in range(i + 1, len(grams)):
            union = grams[i] | grams[j]
            if not union:
                continue
            scores.append((len(grams[i] & grams[j]) / len(union), i, j))
    if not scores:
        return {"pairs": 0, "mean": 0.0, "max": 0.0, "over_threshold": 0,
                "threshold": threshold, "worst": []}
    values = [s for s, _, _ in scores]
    scores.sort(reverse=True)
    return {
        "pairs": len(scores),
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
        "over_threshold": sum(1 for v in values if v >= threshold),
        "threshold": threshold,
        "worst": [{"a": i, "b": j, "score": round(s, 4)} for s, i, j in scores[:5]],
    }
