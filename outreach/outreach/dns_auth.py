"""Sending-domain email-authentication readiness check (SPF / DKIM / DMARC).

Deliverability prerequisite for going live: a cold mailbox on a domain without
SPF + DKIM + DMARC will land in spam regardless of how good the targeting is.
This verifies the records exist (via DNS-over-HTTPS, so no extra dependency) so the
go-live checklist can be confirmed rather than assumed.

CLI:  python -m outreach.dns_auth [domain] [dkim_selector]
"""
from __future__ import annotations
from typing import Optional

import httpx

DOH_ENDPOINT = "https://dns.google/resolve"


def _txt(name: str, *, client=None) -> list[str]:
    owns = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.get(DOH_ENDPOINT, params={"name": name, "type": "TXT"})
        r.raise_for_status()
        answers = r.json().get("Answer", []) or []
        # type 16 == TXT; strip the surrounding quotes DoH includes
        return [a.get("data", "").strip('"') for a in answers if a.get("type") == 16]
    except (httpx.HTTPError, ValueError):
        return []
    finally:
        if owns:
            client.close()


def check_domain(domain: str, *, dkim_selector: str = "google", client=None) -> dict:
    """Return SPF/DKIM/DMARC presence for `domain`. `ready` is all three present.
    DKIM selectors are provider-specific (Google Workspace = `google`)."""
    domain = (domain or "").strip().lower().lstrip("@")
    if not domain:
        return {"domain": domain, "spf": False, "dkim": False, "dmarc": False, "ready": False}
    spf = any(t.lower().startswith("v=spf1") for t in _txt(domain, client=client))
    dmarc = any(t.lower().startswith("v=dmarc1") for t in _txt(f"_dmarc.{domain}", client=client))
    dkim = bool(_txt(f"{dkim_selector}._domainkey.{domain}", client=client))
    return {"domain": domain, "spf": spf, "dkim": dkim, "dmarc": dmarc,
            "ready": spf and dkim and dmarc}


_MX_CACHE: dict[str, bool] = {}


def has_mx(domain: str, *, client=None) -> bool:
    """Can this domain receive mail at all?

    The pre-gate that makes generic guessing affordable: a domain with no mail exchanger
    cannot accept `info@anything`, so probing it spends a verifier credit to learn
    nothing. DNS costs nothing; verifier credits do.

    FAILS OPEN. A DoH outage or a malformed answer returns True, because "we could not
    ask" must never be read as "this domain is dead" — the same mistake the verifier
    chain made with `no_verifier`. Failing open wastes one credit; failing closed
    silently skips a real lead.
    """
    domain = (domain or "").strip().lower().lstrip("@")
    if not domain:
        return False
    if domain in _MX_CACHE:
        return _MX_CACHE[domain]
    owns = client is None
    client = client or httpx.Client(timeout=10)
    try:
        r = client.get(DOH_ENDPOINT, params={"name": domain, "type": "MX"})
        r.raise_for_status()
        data = r.json() or {}
        # NXDOMAIN (3) is a real answer: the domain does not exist.
        result = (False if data.get("Status") == 3
                  else any(a.get("type") == 15 for a in data.get("Answer", []) or []))
    except (httpx.HTTPError, ValueError):
        return True                       # could not ask -> do not penalise the lead
    finally:
        if owns:
            client.close()
    _MX_CACHE[domain] = result
    return result


def domain_of(sender: Optional[str]) -> Optional[str]:
    if not sender:
        return None
    return sender.split("@")[-1].strip().lower() or None


if __name__ == "__main__":
    import sys

    from . import config
    domain = sys.argv[1] if len(sys.argv) > 1 else domain_of(config.GMAIL_SENDER)
    selector = sys.argv[2] if len(sys.argv) > 2 else "google"
    if not domain:
        print("usage: python -m outreach.dns_auth <domain> [dkim_selector]  (or set GMAIL_SENDER)")
        raise SystemExit(2)
    res = check_domain(domain, dkim_selector=selector)
    for k in ("spf", "dkim", "dmarc"):
        print(f"  {k.upper():6} {'ok' if res[k] else 'MISSING'}")
    print(f"  READY  {'yes' if res['ready'] else 'no'}  ({res['domain']})")
