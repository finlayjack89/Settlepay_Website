import uuid

from outreach import inbound


# ---- classification (pure) ----
def test_classify_bounce_by_sender():
    assert inbound.classify({"from_email": "mailer-daemon@outlook.com", "subject": "hi"}) == "bounce"


def test_classify_bounce_by_subject():
    assert inbound.classify({"from_email": "a@b.com", "subject": "Undeliverable: your message"}) == "bounce"


def test_classify_unsubscribe():
    assert inbound.classify({"from_email": "a@b.com", "subject": "re", "body": "please remove me from your list"}) == "unsubscribe"


def test_classify_complaint():
    assert inbound.classify({"from_email": "a@b.com", "body": "this is spam, stop"}) == "complaint"


def test_classify_reply():
    assert inbound.classify({"from_email": "a@b.com", "subject": "re: hello", "body": "sounds good, call me"}) == "reply"


# ---- ingestion (DB, rolled back) ----
def _seed(cur, email, state="sent"):
    cn = f"INB_{uuid.uuid4().hex[:8]}"
    cur.execute(
        "insert into outreach.leads (company_number, company_name, company_type, "
        "subscriber_class, state) values (%s,%s,'ltd','corporate',%s)", (cn, cn, state))
    cur.execute(
        "insert into outreach.enrichment (company_number, website, contact_email, "
        "email_verified, signal) values (%s,'https://x.co',%s,true,'sig')", (cn, email))
    return cn


def test_ingest_unsubscribe_suppresses_and_marks(db_rollback):
    cur = db_rollback.cursor()
    email = f"info-{uuid.uuid4().hex[:6]}@acme.co.uk"
    cn = _seed(cur, email)
    counts = inbound.ingest(
        [{"id": uuid.uuid4().hex, "from_email": email, "subject": "re", "body": "please remove me"}], cur=cur)
    assert counts["unsubscribe"] == 1
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "suppressed"
    cur.execute("select count(*) from outreach.suppressions where lower(email)=lower(%s)", (email,))
    assert cur.fetchone()[0] == 1


def test_ingest_bounce_uses_original_recipient(db_rollback):
    cur = db_rollback.cursor()
    email = f"info-{uuid.uuid4().hex[:6]}@acme.co.uk"
    cn = _seed(cur, email)
    msg = {"id": uuid.uuid4().hex, "from_email": "mailer-daemon@outlook.com",
           "subject": "Undeliverable", "original_recipient": email, "is_ndr": True}
    counts = inbound.ingest([msg], cur=cur)
    assert counts["bounce"] == 1
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "bounced"
    cur.execute("select count(*) from outreach.suppressions where lower(email)=lower(%s)", (email,))
    assert cur.fetchone()[0] == 1


def test_ingest_reply_marks_replied(db_rollback):
    cur = db_rollback.cursor()
    email = f"info-{uuid.uuid4().hex[:6]}@acme.co.uk"
    cn = _seed(cur, email, state="sent")
    counts = inbound.ingest(
        [{"id": uuid.uuid4().hex, "from_email": email, "subject": "re: hello", "body": "yes interested"}], cur=cur)
    assert counts["reply"] == 1
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "replied"


def test_ingest_is_idempotent(db_rollback):
    cur = db_rollback.cursor()
    email = f"info-{uuid.uuid4().hex[:6]}@acme.co.uk"
    _seed(cur, email)
    msg = {"id": uuid.uuid4().hex, "from_email": email, "subject": "re", "body": "unsubscribe please"}
    inbound.ingest([msg], cur=cur)
    counts = inbound.ingest([msg], cur=cur)  # same message again
    assert counts["skipped"] == 1
    cur.execute("select count(*) from outreach.suppressions where lower(email)=lower(%s)", (email,))
    assert cur.fetchone()[0] == 1  # not double-suppressed


def test_inline_source_run(db_rollback):
    cur = db_rollback.cursor()
    email = f"info-{uuid.uuid4().hex[:6]}@acme.co.uk"
    _seed(cur, email)
    src = inbound.InlineMailboxSource(
        [{"id": uuid.uuid4().hex, "from_email": email, "body": "unsubscribe"}])
    counts = inbound.run(source=src, cur=cur)
    assert counts["unsubscribe"] == 1
