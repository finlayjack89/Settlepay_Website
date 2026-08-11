"""Reviewer notes as data — the classifier and what it routes where.

Hermetic apart from the aggregation tests: classify() is a pure function, which is the
point of making it deterministic rather than a model call.
"""
import uuid

import pytest

from outreach import feedback

pytestmark = pytest.mark.floor_h


# --------------------------------------------------------------------------- #
#  The notes a human ACTUALLY wrote — the only ones that have ever existed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("note", [
    "Brand name is yellowstone, not yellow. Not london based but email says london",
    "wrong location",
    "US-bAsed",
])
def test_the_real_rejections_are_all_facts_errors(note):
    """Every substantive note on this database names a wrong CONSTANT, not bad prose.
    That is the finding that set the critic's rubric: a reviewer grading tone would have
    passed all of these."""
    category, stage, confident = feedback.classify(note)
    assert category == "facts_wrong"
    assert stage == "enrich"      # the stage that owns the fix
    assert confident


def test_a_mismatched_contact_routes_to_enrichment_too():
    note = "Lead email doesn't match the company or terminology in the email."
    category, stage, _ = feedback.classify(note)
    assert category == "wrong_recipient" and stage == "enrich"


def test_case_and_spacing_do_not_matter():
    """Real notes are typed fast. 'US-bAsed' is verbatim from the queue."""
    for note in ("WRONG LOCATION", "Wrong    Location", "us-based"):
        assert feedback.classify(note)[0] == "facts_wrong"


# --------------------------------------------------------------------------- #
#  The other families
# --------------------------------------------------------------------------- #
def test_prose_complaints_route_to_the_drafter():
    for note in ("too long", "the tone is off", "subject line is weak", "typo in line 2"):
        category, stage, _ = feedback.classify(note)
        assert category == "copy" and stage == "draft", note


def test_a_lead_we_should_never_have_written_to_routes_to_discovery():
    for note in ("not ICP", "this is a wholesaler", "part of a national chain"):
        category, stage, _ = feedback.classify(note)
        assert category == "not_icp" and stage == "discover", note


def test_an_unrecognised_note_is_other_and_says_so():
    """'other' is a real answer: a human gave a reason we could not place. Forcing it
    into a category would corrupt the aggregate that decides what gets fixed next."""
    category, stage, confident = feedback.classify("hmm, not sure about this one")
    assert category == "other" and stage == "review"
    assert confident is False      # the console can ask rather than guess


def test_no_note_classifies_as_nothing():
    """The absence of a note is not evidence about any stage."""
    for note in (None, "", "   "):
        assert feedback.classify(note) == (None, None, False)


def test_every_category_has_an_owning_stage():
    """A category with no stage is a signal with nowhere to go."""
    for _, pattern in feedback._RULES:
        assert pattern is not None
    for category in ("facts_wrong", "wrong_recipient", "not_icp", "copy", "other"):
        assert feedback.STAGE_FOR[category]


# --------------------------------------------------------------------------- #
#  Storage + aggregation
# --------------------------------------------------------------------------- #
def _rejected(cur, note, *, reviewer="Finlay Salisbury"):
    cn = f"FBK_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,%s,'ltd','corporate','rejected')",
                (cn, cn))
    cur.execute(
        "insert into outreach.drafts (company_number, subject, body_original, "
        "prompt_version, status, reviewer_note, decided_by, decided_at) "
        "values (%s,'s','b','playbook-v3.0','rejected',%s,%s,now()) returning id",
        (cn, note, reviewer))
    return cn, cur.fetchone()[0]


def test_a_classified_note_is_stored_with_its_stage(db_rollback):
    cur = db_rollback.cursor()
    cn, did = _rejected(cur, "wrong location")
    assert feedback.record_note(cur, did, cn, "wrong location") == "facts_wrong"
    cur.execute("select note_category, note_stage from outreach.drafts where id=%s", (did,))
    assert cur.fetchone() == ("facts_wrong", "enrich")


def test_the_backfill_is_idempotent(db_rollback):
    cur = db_rollback.cursor()
    _rejected(cur, "wrong location")
    first = feedback.backfill(cur=cur, limit=500)
    second = feedback.backfill(cur=cur, limit=500)
    assert first["classified"] >= 1
    assert second["classified"] == 0      # nothing left uncategorised


def test_a_bulk_migrations_boilerplate_is_not_reviewer_feedback(db_rollback):
    """352 of the 357 notes on this database are one migration's boilerplate. Counting it
    would report the drafter as the problem 70 times over, on the strength of a note no
    human wrote."""
    cur = db_rollback.cursor()
    cn, did = _rejected(cur, "superseded by playbook v2.0 (was playbook-v2.3)",
                        reviewer="system:v2.0-migration")
    feedback.backfill(cur=cur, limit=500)
    cur.execute("select note_category from outreach.drafts where id=%s", (did,))
    assert cur.fetchone()[0] is None

    cur.execute("update outreach.drafts set note_category='copy', note_stage='draft' "
                "where id=%s", (did,))
    assert cn not in str(feedback.summary(cur, days=90))   # and excluded from the summary


def test_the_summary_names_the_stage_to_fix(db_rollback):
    cur = db_rollback.cursor()
    for note in ("wrong location", "Not london based but email says london", "US-bAsed"):
        cn, did = _rejected(cur, note)
        feedback.record_note(cur, did, cn, note)
    out = feedback.summary(cur, days=90)
    assert out["worst_stage"] == "enrich"
    assert out["by_stage"]["enrich"] >= 3
