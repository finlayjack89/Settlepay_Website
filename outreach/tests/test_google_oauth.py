"""Tests for the shared Google token + Gmail send layer. No network: an injected
fake client captures every call and returns canned responses."""
import base64
import email
import email.policy

import httpx
import pytest

from outreach import config, gmail, google_oauth
from outreach.google_oauth import OAuthNotConfigured


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=None)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._responses.pop(0)


@pytest.fixture
def google_creds(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "cid-1")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "sec-1")
    monkeypatch.setattr(config, "GOOGLE_REFRESH_TOKEN", "ref-1")
    monkeypatch.setattr(config, "GMAIL_SENDER", "finlay@getsettlepay.uk")


def test_access_token_happy_path(google_creds):
    client = FakeClient([FakeResponse({"access_token": "tok-abc"})])
    assert google_oauth.access_token(client=client) == "tok-abc"
    url, kwargs = client.calls[0]
    assert url == "https://oauth2.googleapis.com/token"
    assert kwargs["data"] == {"client_id": "cid-1", "client_secret": "sec-1",
                              "refresh_token": "ref-1", "grant_type": "refresh_token"}
    assert kwargs["timeout"] == 30


@pytest.mark.parametrize("missing", [
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"])
def test_access_token_missing_cred_raises(google_creds, monkeypatch, missing):
    monkeypatch.setattr(config, missing, None)
    client = FakeClient([])
    with pytest.raises(OAuthNotConfigured):
        google_oauth.access_token(client=client)
    assert client.calls == []


def test_access_token_error_response_raises(google_creds):
    client = FakeClient([FakeResponse({"error": "invalid_grant"}, status_code=400)])
    with pytest.raises(httpx.HTTPStatusError):
        google_oauth.access_token(client=client)


def test_send_message_wire_format_and_id(google_creds):
    client = FakeClient([
        FakeResponse({"access_token": "tok-abc"}),
        FakeResponse({"id": "msg-123"}),
    ])
    result = gmail.send_message(
        "sender@getsettlepay.uk", "lead@example.co.uk",
        "A quick question", "Hello,\n\nShort body.", client=client)
    assert result == "msg-123"
    assert len(client.calls) == 2
    url, kwargs = client.calls[1]
    assert url == ("https://gmail.googleapis.com/gmail/v1/users/"
                   "sender@getsettlepay.uk/messages/send")
    assert kwargs["headers"] == {"Authorization": "Bearer tok-abc"}
    assert kwargs["timeout"] == 30
    parsed = email.message_from_bytes(
        base64.urlsafe_b64decode(kwargs["json"]["raw"]), policy=email.policy.default)
    assert parsed["To"] == "lead@example.co.uk"
    assert parsed["From"] == "sender@getsettlepay.uk"
    assert parsed["Subject"] == "A quick question"
    assert parsed.get_content().rstrip("\n") == "Hello,\n\nShort body."


def test_send_message_falls_back_to_config_sender(google_creds):
    client = FakeClient([
        FakeResponse({"access_token": "tok-abc"}),
        FakeResponse({}),
    ])
    result = gmail.send_message(None, "lead@example.co.uk", None, "Body.", client=client)
    assert result == "gmail-accepted"
    url, kwargs = client.calls[1]
    assert "finlay@getsettlepay.uk" in url
    parsed = email.message_from_bytes(
        base64.urlsafe_b64decode(kwargs["json"]["raw"]), policy=email.policy.default)
    assert parsed["From"] == "finlay@getsettlepay.uk"
    assert parsed["Subject"] == ""


def test_send_message_missing_sender_raises(google_creds, monkeypatch):
    monkeypatch.setattr(config, "GMAIL_SENDER", None)
    client = FakeClient([])
    with pytest.raises(OAuthNotConfigured):
        gmail.send_message(None, "lead@example.co.uk", "Subject", "Body.", client=client)
    assert client.calls == []


def test_send_message_missing_creds_raises(google_creds, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_REFRESH_TOKEN", None)
    client = FakeClient([])
    with pytest.raises(OAuthNotConfigured):
        gmail.send_message("sender@getsettlepay.uk", "lead@example.co.uk",
                           "Subject", "Body.", client=client)
    assert client.calls == []
