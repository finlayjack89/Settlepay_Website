"""Email verification — a fallback CHAIN across providers.

The MillionVerifier-ran-dry incident (it returned 200-with-"error" and the pipeline
discarded 178 good leads) is the reason this exists. Now verification tries each provider
in `config.VERIFIER_CHAIN`; when one is OUT OF CREDITS the next takes over, and only when
EVERY provider is out/erroring does the lead defer (a non-answer, never a false verdict).

Each provider normalises to ONE vocabulary the rest of the pipeline already understands:
  'ok'         deliverable            -> contact_tier 'verified'
  'catch_all'  deliverable, unconfirmable -> 'risky'
  'invalid' / 'unknown' / 'disposable'    -> discarded
  'error' / 'verify_error' (TRANSIENT)    -> DEFERRED (retried later)

Provider quirk handled explicitly (learned by testing the live APIs, not assumed):
a ROLE address (info@, sales@) is exactly what a B2B PECR pipeline wants, but ZeroBounce
reports it as `do_not_mail / role_based` and Reoon as `role_account`. Both are mapped to
'ok', so the fallback never rejects the very addresses we target.
"""
from __future__ import annotations

import abc
from typing import Optional

import httpx

from . import config

# results that are a real verdict about the address (stop the chain)
VERDICTS = frozenset({"ok", "catch_all", "invalid", "unknown", "disposable"})
# results that mean "no answer" — try the next provider, and if none answers, defer
TRANSIENT_RESULTS = ("error", "verify_error")

# providers that reported out-of-credits THIS PROCESS — skip them for the rest of the run
# (mirrors the enrich circuit breaker: don't hammer a dead provider). Reset on restart.
_EXHAUSTED: set[str] = set()


class Provider(abc.ABC):
    name: str = ""
    cost_gbp: float = 0.0            # per verification (free tiers = 0)

    @abc.abstractmethod
    def key(self) -> Optional[str]:
        ...

    def enabled(self) -> bool:
        return bool(self.key())

    @abc.abstractmethod
    def check(self, email: str, client: httpx.Client) -> tuple[str, bool]:
        """Return (canonical_result, out_of_credits). A transient failure returns
        ('error', False); running out of credits returns ('error', True)."""
        ...


class MillionVerifier(Provider):
    name = "millionverifier"
    cost_gbp = config.MV_COST_GBP_PER_VERIFY

    def key(self):
        return config.MILLIONVERIFIER_API_KEY

    def check(self, email, client):
        try:
            r = client.get("https://api.millionverifier.com/api/v3/",
                           params={"api": self.key(), "email": email}, timeout=25)
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return "error", False
        result = str(data.get("result", "error"))
        err = str(data.get("error", "")).lower()
        if result == "error" and ("credit" in err or "insufficient" in err):
            return "error", True
        mapping = {"ok": "ok", "catch_all": "catch_all", "unknown": "unknown",
                   "invalid": "invalid", "disposable": "invalid"}
        return mapping.get(result, "error"), False


class Reoon(Provider):
    name = "reoon"
    cost_gbp = 0.0

    def key(self):
        return config.REOON_API_KEY

    def check(self, email, client):
        try:
            r = client.get("https://emailverifier.reoon.com/api/v1/verify",
                           params={"email": email, "key": self.key(), "mode": "power"},
                           timeout=40)
        except httpx.HTTPError:
            return "error", False
        if r.status_code in (402, 403, 429):        # payment/limit/rate -> out of capacity
            return "error", True
        try:
            d = r.json()
        except ValueError:
            return "error", False
        # an error/limit payload rather than a verdict
        status = str(d.get("status", "")).lower()
        if status in ("error",) or "error" in d or "is_deliverable" not in d:
            msg = f"{d.get('error','')} {d.get('message','')}".lower()
            return "error", ("credit" in msg or "limit" in msg or "quota" in msg)
        if d.get("is_catch_all"):
            return "catch_all", False
        if d.get("is_disposable") or d.get("is_spamtrap"):
            return "invalid", False
        # role accounts (info@) come back safe_to_send/role_account — that's a valid B2B target
        if d.get("is_deliverable") or d.get("is_safe_to_send"):
            return "ok", False
        if status == "unknown" or not d.get("mx_accepts_mail", True):
            return "unknown", False
        return "invalid", False


class ZeroBounce(Provider):
    name = "zerobounce"
    cost_gbp = 0.0

    def key(self):
        return config.ZEROBOUNCE_API_KEY

    def check(self, email, client):
        try:
            r = client.get("https://api.zerobounce.net/v2/validate",
                           params={"api_key": self.key(), "email": email}, timeout=40)
            d = r.json()
        except (httpx.HTTPError, ValueError):
            return "error", False
        if "error" in d and "status" not in d:      # {"error": "...ran out of credits"}
            return "error", "credit" in str(d["error"]).lower()
        status = str(d.get("status", "")).lower()
        sub = str(d.get("sub_status", "")).lower()
        if status == "valid":
            return "ok", False
        if status == "catch-all" or d.get("catchall_domain") in (True, "true"):
            return "catch_all", False
        # ZeroBounce flags a ROLE address as do_not_mail/role_based — but a role mailbox is
        # exactly our B2B target, so it is deliverable, not a rejection.
        if status == "do_not_mail" and sub == "role_based":
            return "ok", False
        if status == "unknown":
            return "unknown", False
        return "invalid", False                     # invalid / spamtrap / abuse / other do_not_mail


_REGISTRY = {p.name: p for p in (MillionVerifier(), Reoon(), ZeroBounce())}


def _chain() -> list[Provider]:
    return [_REGISTRY[n] for n in config.VERIFIER_CHAIN
            if n in _REGISTRY and _REGISTRY[n].enabled()]


def verify_email(email: str, *, client: Optional[httpx.Client] = None,
                 **_ignore) -> tuple[bool, str]:
    """Verify `email` across the provider chain. Returns (deliverable, result) where
    result is the canonical vocabulary. All providers out/erroring -> (False,
    'verify_error') so the caller DEFERS rather than discards. (**_ignore keeps the old
    `api_key=`/`retries=` call sites working during the migration.)"""
    own = client is None
    client = client or httpx.Client(timeout=40)
    tried = False
    try:
        for provider in _chain():
            if provider.name in _EXHAUSTED:
                continue
            tried = True
            result, out_of_credits = provider.check(email, client)
            if out_of_credits:
                _EXHAUSTED.add(provider.name)
                continue                            # dead provider -> next in the chain
            if result in TRANSIENT_RESULTS:
                continue                            # transient blip -> try the next one
            _meter(provider)
            return (result == "ok", result)
        # nobody could answer: a non-answer, never a verdict
        return (False, "verify_error" if tried else "no_verifier")
    finally:
        if own:
            client.close()


def _meter(provider: Provider) -> None:
    try:
        from . import spend
        spend.record(provider.name, purpose="verify", units_in=1, cost_gbp=provider.cost_gbp)
    except Exception:
        pass                                        # metering never fails a verification


def reset_exhausted() -> None:
    """Clear the per-run out-of-credits memory (e.g. after topping a provider up)."""
    _EXHAUSTED.clear()
