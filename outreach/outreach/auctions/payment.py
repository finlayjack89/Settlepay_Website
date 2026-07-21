"""Payment-method detection — the wedge, in code.

The single strongest SettlePay signal is an auctioneer telling winners to pay by a
MANUAL method: bank transfer, BACS, cheque, cash on collection, or a card taken over the
phone. That is literal proof of the pain — no online card page, reconciliation done by
hand. This module finds those phrases on the auctioneer's own site and captures the
EXACT sentence, so the drafter can quote it back ("you ask winners to pay by bank
transfer within three days…").

A house that already says "pay online by card / secure checkout" is a weaker fit — they
may already have what SettlePay sells — so that is detected too and lowers the score.
"""
from __future__ import annotations

import re

# method -> matching pattern. Order matters only for reporting; detection is a set.
_METHODS = {
    "bank transfer": r"bank transfer|bank\s*trans|direct transfer|faster payment",
    "bacs": r"\bbacs\b|\bchaps\b",
    "cheque": r"\bcheques?\b",
    "cash": r"cash on collection|cash on|paid in cash|\bcash\b(?!\s*(only\s*)?machine)",
    "card over the phone": r"card (payment )?over the (tele)?phone|telephone.{0,15}card|"
                           r"card details over|phone.{0,10}card payment",
    "card in person": r"card (payments? )?(on|upon|in person|at) collection|"
                      r"chip (and|&) pin|card machine",
    "online card": r"pay(ment)? online|online payment|secure (online )?checkout|"
                   r"pay by card online|worldpay|stripe|opayo|sagepay|paypal|"
                   r"add to basket|online card payment",
}
_COMPILED = {m: re.compile(p, re.I) for m, p in _METHODS.items()}

# the manual methods that make a strong SettlePay lead
MANUAL = frozenset({"bank transfer", "bacs", "cheque", "cash", "card over the phone"})
# already-has-online-card — weakens the fit
ONLINE = frozenset({"online card"})

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def detect(text: str) -> dict:
    """From page text, return {methods, manual, online, quote}. `quote` is the exact
    sentence carrying the strongest manual signal — the drafter's hook — or the best
    payment sentence found. Empty result when the site says nothing about payment."""
    if not text:
        return {"methods": [], "manual": False, "online": False, "quote": None}
    methods = [m for m, pat in _COMPILED.items() if pat.search(text)]
    manual = bool(set(methods) & MANUAL)
    online = bool(set(methods) & ONLINE)

    quote = None
    # prefer a sentence that states a MANUAL method; fall back to any payment sentence
    for wanted in (MANUAL, set(methods)):
        for sent in _SENT_SPLIT.split(text):
            s = sent.strip()
            if 15 <= len(s) <= 240 and any(_COMPILED[m].search(s) for m in wanted):
                quote = " ".join(s.split())
                break
        if quote:
            break
    return {"methods": methods, "manual": manual, "online": online, "quote": quote}


# where "how do I pay" usually lives, tried in likely order
PAYMENT_PATHS = ("", "/terms", "/terms-and-conditions", "/terms-conditions", "/how-to-buy",
                 "/how-to-bid", "/buying", "/buyers", "/payment", "/payments", "/faq",
                 "/faqs", "/information", "/conditions-of-sale")
