"""Verifier chain — provider result mapping + fallover, all offline via a fake client."""
import json

import pytest

from outreach import config, verify

pytestmark = pytest.mark.floor_d


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    """Returns a canned response keyed by which provider's host is called."""
    def __init__(self, mv=None, reoon=None, zb=None):
        self._by_host = {"millionverifier": mv, "reoon": reoon, "zerobounce": zb}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        host = ("millionverifier" if "millionverifier" in url else
                "reoon" if "reoon" in url else "zerobounce")
        self.calls.append(host)
        resp = self._by_host[host]
        if resp is None:
            return _Resp({}, status=200)
        return resp


@pytest.fixture(autouse=True)
def _all_keys(monkeypatch):
    monkeypatch.setattr(config, "MILLIONVERIFIER_API_KEY", "mv")
    monkeypatch.setattr(config, "REOON_API_KEY", "re")
    monkeypatch.setattr(config, "ZEROBOUNCE_API_KEY", "zb")
    monkeypatch.setattr(config, "VERIFIER_CHAIN", ["millionverifier", "reoon", "zerobounce"])
    verify.reset_exhausted()
    yield
    verify.reset_exhausted()


# --- MillionVerifier mapping ---
@pytest.mark.parametrize("result,expected", [
    ("ok", "ok"), ("catch_all", "catch_all"), ("invalid", "invalid"),
    ("disposable", "invalid"), ("unknown", "unknown")])
def test_millionverifier_mapping(result, expected):
    c = _FakeClient(mv=_Resp({"result": result}))
    assert verify.MillionVerifier().check("a@b.co", c) == (expected, False)


def test_millionverifier_out_of_credits_is_flagged():
    c = _FakeClient(mv=_Resp({"result": "error", "error": "Insufficient credits"}))
    assert verify.MillionVerifier().check("a@b.co", c) == ("error", True)


# --- Reoon mapping (role account = deliverable, the B2B target) ---
def test_reoon_role_account_is_ok():
    c = _FakeClient(reoon=_Resp({"status": "role_account", "is_deliverable": True,
                                 "is_safe_to_send": True, "is_catch_all": False,
                                 "mx_accepts_mail": True}))
    assert verify.Reoon().check("info@b.co", c) == ("ok", False)


def test_reoon_catch_all_and_invalid():
    ca = _FakeClient(reoon=_Resp({"is_catch_all": True, "is_deliverable": True}))
    assert verify.Reoon().check("a@b.co", ca) == ("catch_all", False)
    bad = _FakeClient(reoon=_Resp({"is_deliverable": False, "is_catch_all": False,
                                   "mx_accepts_mail": True, "status": "invalid"}))
    assert verify.Reoon().check("a@b.co", bad) == ("invalid", False)


def test_reoon_out_of_credits():
    c = _FakeClient(reoon=_Resp({"error": "monthly limit reached"}))
    assert verify.Reoon().check("a@b.co", c) == ("error", True)


# --- ZeroBounce mapping (role address reported do_not_mail/role_based -> still ok) ---
def test_zerobounce_role_based_is_ok_not_rejected():
    c = _FakeClient(zb=_Resp({"status": "do_not_mail", "sub_status": "role_based"}))
    assert verify.ZeroBounce().check("info@b.co", c) == ("ok", False)


@pytest.mark.parametrize("status,sub,expected", [
    ("valid", "", "ok"), ("catch-all", "", "catch_all"), ("invalid", "mailbox_not_found", "invalid"),
    ("unknown", "", "unknown"), ("spamtrap", "", "invalid"),
    ("do_not_mail", "toxic", "invalid")])
def test_zerobounce_status_mapping(status, sub, expected):
    c = _FakeClient(zb=_Resp({"status": status, "sub_status": sub}))
    assert verify.ZeroBounce().check("a@b.co", c)[0] == expected


def test_zerobounce_out_of_credits():
    c = _FakeClient(zb=_Resp({"error": "Invalid API Key or your account ran out of credits"}))
    assert verify.ZeroBounce().check("a@b.co", c) == ("error", True)


# --- the chain ---
def test_chain_fails_over_when_primary_is_out_of_credits():
    c = _FakeClient(mv=_Resp({"result": "error", "error": "Insufficient credits"}),
                    reoon=_Resp({"is_deliverable": True, "is_catch_all": False}))
    assert verify.verify_email("info@b.co", client=c) == (True, "ok")
    assert "millionverifier" in verify._EXHAUSTED           # marked, will be skipped next time


def test_exhausted_provider_is_skipped_on_the_next_call():
    c = _FakeClient(mv=_Resp({"result": "error", "error": "Insufficient credits"}),
                    reoon=_Resp({"is_deliverable": True}))
    verify.verify_email("a@b.co", client=c)
    c.calls.clear()
    verify.verify_email("c@d.co", client=c)
    assert "millionverifier" not in c.calls                 # not probed again this run
    assert "reoon" in c.calls


def test_all_providers_out_defers_never_a_false_verdict():
    c = _FakeClient(mv=_Resp({"result": "error", "error": "Insufficient credits"}),
                    reoon=_Resp({"error": "limit reached"}),
                    zb=_Resp({"error": "ran out of credits"}))
    ok, result = verify.verify_email("a@b.co", client=c)
    assert ok is False and result in verify.TRANSIENT_RESULTS   # DEFER, not discard


def test_a_real_invalid_stops_the_chain():
    """A provider answering 'invalid' is a verdict — don't fall through to another."""
    c = _FakeClient(mv=_Resp({"result": "invalid"}),
                    reoon=_Resp({"is_deliverable": True}))   # would say ok, must not be reached
    assert verify.verify_email("a@b.co", client=c) == (False, "invalid")
    assert "reoon" not in c.calls


def test_no_configured_verifier_defers():
    import outreach.config as cfg
    for k in ("MILLIONVERIFIER_API_KEY", "REOON_API_KEY", "ZEROBOUNCE_API_KEY"):
        setattr(cfg, k, None)
    ok, result = verify.verify_email("a@b.co", client=_FakeClient())
    assert ok is False and result == "no_verifier"
