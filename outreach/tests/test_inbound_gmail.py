import base64

from outreach import config, inbound


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _plain_msg(mid="m1", frm="Jane <jane@acme.co.uk>", subject="Re: your note",
               body="Thanks, tell me more."):
    return {"id": mid, "threadId": "t1", "payload": {
        "mimeType": "text/plain",
        "headers": [{"name": "From", "value": frm},
                    {"name": "Subject", "value": subject},
                    {"name": "Date", "value": "Tue, 21 Jul 2026 10:00:00 +0100"}],
        "body": {"data": _b64(body)},
    }}


def _dsn_msg(mid="m2", failed="info@dead-domain.co.uk"):
    status = f"Reporting-MTA: dns; google.com\nFinal-Recipient: rfc822; <{failed}>\nAction: failed\n"
    return {"id": mid, "threadId": "t2", "payload": {
        "mimeType": "multipart/report",
        "headers": [{"name": "From", "value": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"},
                    {"name": "Subject", "value": "Delivery Status Notification (Failure)"}],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("Address not found.")}},
            {"mimeType": "message/delivery-status", "body": {"data": _b64(status)}},
        ],
    }}


def test_parse_plain_reply():
    m = inbound._parse_gmail_message(_plain_msg())
    assert m["id"] == "m1" and m["from_email"] == "jane@acme.co.uk"
    assert m["subject"] == "Re: your note" and "tell me more" in m["body"]
    assert m["is_ndr"] is False and m["original_recipient"] is None
    assert inbound.classify(m) == "reply"


def test_parse_dsn_extracts_original_recipient():
    m = inbound._parse_gmail_message(_dsn_msg())
    assert m["is_ndr"] is True
    assert m["original_recipient"] == "info@dead-domain.co.uk"
    assert inbound.classify(m) == "bounce"


def test_html_fallback_body():
    msg = _plain_msg()
    msg["payload"]["mimeType"] = "text/html"
    msg["payload"]["body"] = {"data": _b64("<p>please <b>unsubscribe</b> me</p>")}
    m = inbound._parse_gmail_message(msg)
    assert "unsubscribe" in m["body"] and "<" not in m["body"]
    assert inbound.classify(m) == "unsubscribe"


class _FakeGmailClient:
    """Answers the token POST plus the list/get GETs the reader makes."""

    def __init__(self, messages):
        self._messages = {m["id"]: m for m in messages}
        self.calls = []

    def post(self, url, **kw):
        self.calls.append(("post", url))

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"access_token": "tok"}
        return R()

    def get(self, url, **kw):
        self.calls.append(("get", url))
        msgs = self._messages

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self_inner):
                if url.endswith("/messages"):
                    return {"messages": [{"id": i} for i in msgs]}
                return msgs[url.rsplit("/", 1)[1]]
        return R()


def test_gmail_source_fetches_and_parses(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setattr(config, "GOOGLE_REFRESH_TOKEN", "ref")
    fake = _FakeGmailClient([_plain_msg(), _dsn_msg()])
    src = inbound.GmailMailboxSource(client=fake, sender="finlay@settlepaygroup.uk")
    out = src.fetch()
    assert {m["id"] for m in out} == {"m1", "m2"}
    kinds = {m["id"]: inbound.classify(m) for m in out}
    assert kinds == {"m1": "reply", "m2": "bounce"}


def test_gmail_source_respects_cap(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(config, "GOOGLE_CLIENT_SECRET", "sec")
    monkeypatch.setattr(config, "GOOGLE_REFRESH_TOKEN", "ref")
    fake = _FakeGmailClient([_plain_msg(f"m{i}") for i in range(10)])
    src = inbound.GmailMailboxSource(client=fake, sender="x@y.co", max_messages=3)
    assert len(src.fetch()) == 3


def test_ingest_roundtrip_from_parsed_gmail(db_rollback):
    cur = db_rollback.cursor()
    parsed = [inbound._parse_gmail_message(_plain_msg()),
              inbound._parse_gmail_message(_dsn_msg())]
    counts = inbound.ingest(parsed, cur=cur)
    assert counts["reply"] == 1 and counts["bounce"] == 1
    counts2 = inbound.ingest(parsed, cur=cur)  # idempotent on message id
    assert counts2["skipped"] == 2
    cur.execute("select count(*) from outreach.suppressions where email=%s",
                ("info@dead-domain.co.uk",))
    assert cur.fetchone()[0] == 1
