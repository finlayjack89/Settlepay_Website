import time

import pytest

from outreach import config, webauth

SA = "tick-invoker@proj.iam.gserviceaccount.com"
AUD = "https://ops-console-xyz.a.run.app"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "SESSION_SECRET", "test-secret")
    monkeypatch.setattr(config, "SESSION_TTL_HOURS", 12)
    monkeypatch.setattr(config, "CONSOLE_PASSWORD_HASH", webauth.hash_password("hunter2"))


def test_cookie_name():
    assert webauth.COOKIE_NAME == "ops_session"


def test_auth_configured_combinations(monkeypatch):
    for secret, pwhash, expected in [
        ("s", "h", True), (None, "h", False), ("s", None, False), (None, None, False),
    ]:
        monkeypatch.setattr(config, "SESSION_SECRET", secret)
        monkeypatch.setattr(config, "CONSOLE_PASSWORD_HASH", pwhash)
        assert webauth.auth_configured() is expected


def test_password_roundtrip(configured):
    assert webauth.verify_password("hunter2") is True
    assert webauth.verify_password("wrong") is False
    assert webauth.verify_password("") is False


def test_verify_password_unset_hash(monkeypatch):
    monkeypatch.setattr(config, "CONSOLE_PASSWORD_HASH", None)
    assert webauth.verify_password("hunter2") is False


def test_verify_password_garbage_hash(monkeypatch):
    monkeypatch.setattr(config, "CONSOLE_PASSWORD_HASH", "not-an-argon2-hash")
    assert webauth.verify_password("hunter2") is False


def test_session_roundtrip(configured):
    token = webauth.create_session()
    assert webauth.verify_session(token) is True
    assert webauth.verify_session(None) is False
    assert webauth.verify_session("") is False


def test_session_expired(configured, monkeypatch):
    token = webauth.create_session()
    monkeypatch.setattr(config, "SESSION_TTL_HOURS", 0)
    # itsdangerous measures age in whole seconds; skew its clock forward rather
    # than sleeping across a second boundary
    from itsdangerous.timed import TimestampSigner
    monkeypatch.setattr(TimestampSigner, "get_timestamp", lambda self: int(time.time()) + 10)
    assert webauth.verify_session(token) is False


def test_session_tampered(configured):
    # Tamper in the MIDDLE, not at the end. The signature is 20 bytes -> 27 base64url
    # chars, and 27x6 = 162 bits carries 2 spare: the final character always has its
    # low bits clear, so 'A' and 'B' there decode to identical bytes. Flipping the last
    # char was therefore a no-op whenever it happened to be 'A' (~1 run in 16) and the
    # test failed at that rate for reasons nothing to do with the code under test.
    token = webauth.create_session()
    i = len(token) // 2
    tampered = token[:i] + ("A" if token[i] != "A" else "Z") + token[i + 1:]
    assert tampered != token
    assert webauth.verify_session(tampered) is False


def test_session_wrong_secret(configured, monkeypatch):
    token = webauth.create_session()
    monkeypatch.setattr(config, "SESSION_SECRET", "rotated-secret")
    assert webauth.verify_session(token) is False


def test_csrf_roundtrip(configured):
    token = webauth.create_session()
    csrf = webauth.csrf_token(token)
    assert webauth.verify_csrf(token, csrf) is True
    assert webauth.verify_csrf(token, csrf + "x") is False
    assert webauth.verify_csrf(token, None) is False
    assert webauth.verify_csrf(None, csrf) is False


def test_rate_limiter_blocks_then_resets():
    rl = webauth.LoginRateLimiter(max_attempts=3, window_secs=300)
    assert rl.allow("1.2.3.4") is True
    for _ in range(3):
        rl.record_failure("1.2.3.4")
    assert rl.allow("1.2.3.4") is False
    assert rl.allow("5.6.7.8") is True
    rl.reset("1.2.3.4")
    assert rl.allow("1.2.3.4") is True


def test_rate_limiter_window_expiry():
    rl = webauth.LoginRateLimiter(max_attempts=1, window_secs=0)
    rl.record_failure("1.2.3.4")
    time.sleep(0.01)
    assert rl.allow("1.2.3.4") is True


def _tick_config(monkeypatch, sa=SA, aud=AUD):
    monkeypatch.setattr(config, "TICK_INVOKER_SA", sa)
    monkeypatch.setattr(config, "TICK_AUDIENCE", aud)


def test_tick_happy_path(monkeypatch):
    _tick_config(monkeypatch)
    seen = {}

    def fake_verifier(token):
        seen["token"] = token
        return {"email": SA, "email_verified": True, "aud": AUD}

    assert webauth.verify_tick_request("Bearer good-token", verifier=fake_verifier) is True
    assert seen["token"] == "good-token"


def test_tick_wrong_sa_email(monkeypatch):
    _tick_config(monkeypatch)
    verifier = lambda t: {"email": "evil@example.com", "email_verified": True}
    assert webauth.verify_tick_request("Bearer t", verifier=verifier) is False


def test_tick_email_not_verified(monkeypatch):
    _tick_config(monkeypatch)
    verifier = lambda t: {"email": SA, "email_verified": False}
    assert webauth.verify_tick_request("Bearer t", verifier=verifier) is False


def test_tick_missing_or_malformed_header(monkeypatch):
    _tick_config(monkeypatch)
    verifier = lambda t: {"email": SA, "email_verified": True}
    assert webauth.verify_tick_request(None, verifier=verifier) is False
    assert webauth.verify_tick_request("", verifier=verifier) is False
    assert webauth.verify_tick_request("Basic abc", verifier=verifier) is False
    assert webauth.verify_tick_request("Bearer ", verifier=verifier) is False


def test_tick_verifier_raises(monkeypatch):
    _tick_config(monkeypatch)

    def boom(token):
        raise ValueError("bad signature")

    assert webauth.verify_tick_request("Bearer t", verifier=boom) is False


def test_tick_unset_config(monkeypatch):
    verifier = lambda t: {"email": SA, "email_verified": True}
    _tick_config(monkeypatch, sa=None)
    assert webauth.verify_tick_request("Bearer t", verifier=verifier) is False
    _tick_config(monkeypatch, aud=None)
    assert webauth.verify_tick_request("Bearer t", verifier=verifier) is False
