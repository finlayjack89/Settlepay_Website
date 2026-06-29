from outreach import dns_auth


class _FakeResp:
    def __init__(self, answers):
        self._a = answers

    def raise_for_status(self):
        pass

    def json(self):
        return {"Answer": self._a}


class _FakeDoH:
    """Stub DNS-over-HTTPS client: maps a query name to its TXT records."""

    def __init__(self, mapping):
        self.mapping = mapping

    def get(self, url, params=None):
        txts = self.mapping.get(params["name"], [])
        return _FakeResp([{"type": 16, "data": f'"{t}"'} for t in txts])


def test_check_domain_ready():
    m = {
        "acme.co.uk": ["v=spf1 include:spf.protection.outlook.com -all"],
        "_dmarc.acme.co.uk": ["v=DMARC1; p=quarantine; rua=mailto:dmarc@acme.co.uk"],
        "selector1._domainkey.acme.co.uk": ["v=DKIM1; k=rsa; p=ABCDEF"],
    }
    res = dns_auth.check_domain("acme.co.uk", client=_FakeDoH(m))
    assert res["spf"] and res["dkim"] and res["dmarc"] and res["ready"] is True


def test_check_domain_missing_dmarc_not_ready():
    m = {
        "acme.co.uk": ["v=spf1 -all"],
        "selector1._domainkey.acme.co.uk": ["v=DKIM1; p=x"],
    }
    res = dns_auth.check_domain("acme.co.uk", client=_FakeDoH(m))
    assert res["spf"] and res["dkim"] and res["dmarc"] is False and res["ready"] is False


def test_domain_of():
    assert dns_auth.domain_of("hello@settlepayhq.uk") == "settlepayhq.uk"
    assert dns_auth.domain_of(None) is None
