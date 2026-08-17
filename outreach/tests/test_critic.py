"""The critic — decorrelation, the verdict parse, and the shadow-mode contract.

Hermetic: the provider is faked. No OpenAI call, no spend. The load-bearing properties
are that it cannot silently become the drafter's own family, that it never crashes the
stage, and that in shadow mode it changes nothing at all.
"""
import json
import uuid

import pytest

from outreach import config, critic, llm

pytestmark = pytest.mark.floor_h


class _FakeProvider:
    def __init__(self, payload, *, model="gpt-5.6-luna"):
        self.payload, self.model, self.prompts = payload, model, []

    def complete(self, prompt, *, purpose, max_words=None, schema=None):
        self.prompts.append(prompt)
        if isinstance(self.payload, Exception):
            raise self.payload
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return llm.LLMResult(text, "openai", {"purpose": purpose, "model": self.model})


# --------------------------------------------------------------------------- #
#  Decorrelation — the whole reason this module exists
# --------------------------------------------------------------------------- #
def test_the_critic_is_not_the_drafters_family(monkeypatch):
    """A judge drawn from the generator's own family shares its blind spots and returns
    confident, correlated verdicts. The drafting bench had to be re-run once for exactly
    that reason. If these ever resolve to the same provider the critic stops being
    evidence, and it fails SILENTLY — it would still return verdicts."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "gemini")
    monkeypatch.setattr(config, "CRITIC_PROVIDER", "openai")
    assert llm.draft_provider().name != llm.critic_provider().name


def test_the_luna_budget_floor_is_enforced(monkeypatch):
    """Reasoning is spent from max_completion_tokens BEFORE any output, so too small a
    budget returns an empty string rather than an error — a critic that silently passes
    everything. The floor is the defence."""
    monkeypatch.setattr(config, "OPENAI_MAX_COMPLETION_TOKENS", 10)
    captured = {}

    class _Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    captured.update(kw)
                    raise RuntimeError("stop here — we only wanted the kwargs")

    p = llm.OpenAIProvider(client=_Client())
    with pytest.raises(llm.LLMUnavailable):
        p.complete("x", purpose="critic")
    assert captured["max_completion_tokens"] >= llm.OpenAIProvider.MIN_COMPLETION_TOKENS
    # the reasoning family rejects max_tokens outright
    assert "max_tokens" not in captured


def test_openai_is_billed_as_cash_not_credit():
    from outreach import spend
    assert "openai" in spend.CASH_PROVIDERS and "openai" not in spend.CREDIT_PROVIDERS
    # Luna at $1/$6 per 1M — 1M in + 1M out
    assert round(spend.openai_cost_gbp("gpt-5.6-luna", 1_000_000, 1_000_000), 2) == \
        round(7.0 * spend.config.USD_TO_GBP, 2)


def test_an_unpriced_model_is_charged_at_the_top_rate():
    """Never silently under-priced: a cap gate reading a too-low number is a cap gate
    that does not gate."""
    from outreach import spend
    assert spend.openai_cost_gbp("gpt-5.6-unknown", 1_000_000, 0) >= \
        spend.openai_cost_gbp("gpt-5.6-sol", 1_000_000, 0)


# --------------------------------------------------------------------------- #
#  The verdict parse
# --------------------------------------------------------------------------- #
def test_a_hard_reason_fails_the_draft_whatever_the_model_called_it():
    """The model does not get the last word on its own consistency. A hard failure IS a
    failure by definition — otherwise a confident model can talk itself into a pass."""
    out = critic.parse_verdict(json.dumps({
        "score": 95, "verdict": "pass",
        "reasons": [{"dimension": "grounding", "severity": "hard",
                     "detail": "says London, facts say Otley"}]}))
    assert out["verdict"] == "fail"


def test_a_score_below_the_bar_fails_even_with_no_hard_reason(monkeypatch):
    monkeypatch.setattr(config, "CRITIC_PASS_SCORE", 70)
    out = critic.parse_verdict(json.dumps({"score": 40, "verdict": "pass", "reasons": []}))
    assert out["verdict"] == "fail"


def test_a_clean_draft_passes(monkeypatch):
    monkeypatch.setattr(config, "CRITIC_PASS_SCORE", 70)
    out = critic.parse_verdict(json.dumps({"score": 88, "verdict": "pass", "reasons": []}))
    assert out["verdict"] == "pass" and out["score"] == 88


def test_json_wrapped_in_prose_or_fences_still_parses():
    fenced = "```json\n{\"score\": 80, \"verdict\": \"pass\", \"reasons\": []}\n```"
    assert critic.parse_verdict(fenced)["score"] == 80
    chatty = 'Here is my assessment:\n{"score": 80, "verdict": "pass", "reasons": []}\nHope that helps.'
    assert critic.parse_verdict(chatty)["score"] == 80


@pytest.mark.parametrize("bad", ["not json at all", '{"verdict": "pass"}',
                                 '{"score": 500, "verdict": "pass", "reasons": []}'])
def test_an_unreadable_verdict_raises_rather_than_guessing(bad):
    with pytest.raises(ValueError):
        critic.parse_verdict(bad)


# --------------------------------------------------------------------------- #
#  The prompt
# --------------------------------------------------------------------------- #
def test_the_critic_sees_the_recipient_the_drafter_never_saw():
    """"Lead email doesn't match the company" was a real rejection, and the drafter
    cannot catch it — it is never shown the address its words will be sent to."""
    from outreach import facts
    prompt = critic.build_prompt(
        company_name="Naish Estate Agents", subject="s", body="b",
        fact_block=facts.loads(None), contact_email="someone@othercompany.co.uk",
        website="https://naishproperty.co.uk", vertical="estate agents")
    assert "someone@othercompany.co.uk" in prompt
    assert "https://naishproperty.co.uk" in prompt


def test_the_rubric_names_the_failures_that_actually_happened():
    """The rubric is built from this pipeline's real rejections, not from what a good
    email looks like. Every human rejection was a facts error; a rubric weighted toward
    prose would have passed all of them."""
    r = critic.RUBRIC.lower()
    assert "town" in r and "company name" in r     # the two most-rejected constants
    assert "fca" in r and "pci" in r               # the compliance hard-fails
    for dimension in critic.HARD_DIMENSIONS:
        assert dimension in r


# --------------------------------------------------------------------------- #
#  Shadow mode: it decides NOTHING
# --------------------------------------------------------------------------- #
def _awaiting(cur):
    cn = f"CRT_{uuid.uuid4().hex[:8]}"
    cur.execute("insert into outreach.leads (company_number, company_name, company_type, "
                "subscriber_class, state) values (%s,%s,'ltd','corporate','drafted')",
                (cn, cn))
    cur.execute("insert into outreach.enrichment (company_number, contact_email, website, "
                "facts) values (%s,'info@x.co.uk','https://x.co.uk','{}'::jsonb)", (cn,))
    cur.execute("insert into outreach.drafts (company_number, subject, body_original, "
                "prompt_version, status) values (%s,'s','b','playbook-v3.0',"
                "'awaiting_approval') returning id", (cn,))
    return cn, cur.fetchone()[0]


@pytest.fixture
def critic_on(monkeypatch):
    monkeypatch.setattr(config, "CRITIC_ENABLED", True)
    monkeypatch.setattr(config, "CRITIC_MODE", "shadow")


def test_disabled_by_default_it_does_nothing(db_rollback):
    assert "skipped" in critic.run(cur=db_rollback.cursor())


def test_a_failing_verdict_leaves_the_draft_exactly_where_it_was(db_rollback, critic_on):
    """Shadow mode is the whole contract: it records what it thinks and changes nothing,
    so its agreement with real human decisions can be measured before it is trusted."""
    cur = db_rollback.cursor()
    cn, did = _awaiting(cur)
    provider = _FakeProvider({"score": 10, "verdict": "fail",
                              "reasons": [{"dimension": "grounding", "severity": "hard",
                                           "detail": "invented a town"}]})
    critic.run(limit=50, cur=cur, provider=provider)

    cur.execute("select status, decided_by, critic_verdict, critic_score, critic_model "
                "from outreach.drafts where id=%s", (did,))
    status, decided_by, verdict, score, model = cur.fetchone()
    assert status == "awaiting_approval" and decided_by is None   # untouched
    assert verdict == "fail" and score == 10 and model == "gpt-5.6-luna"
    cur.execute("select state::text from outreach.leads where company_number=%s", (cn,))
    assert cur.fetchone()[0] == "drafted"


def test_an_unreachable_critic_never_breaks_the_stage(db_rollback, critic_on):
    """The pipeline must never hard-block on an LLM. An error is a fact about the critic,
    not a judgement about the draft — and the draft must not be re-judged for ever."""
    cur = db_rollback.cursor()
    _, did = _awaiting(cur)
    out = critic.run(limit=50, cur=cur, provider=_FakeProvider(RuntimeError("502")))
    assert out["errored"] >= 1
    cur.execute("select critic_verdict, critic_at is not null from outreach.drafts "
                "where id=%s", (did,))
    assert cur.fetchone() == ("error", True)


def test_a_judged_draft_is_not_judged_twice(db_rollback, critic_on):
    cur = db_rollback.cursor()
    _awaiting(cur)
    provider = _FakeProvider({"score": 90, "verdict": "pass", "reasons": []})
    first = critic.run(limit=50, cur=cur, provider=provider)
    second = critic.run(limit=50, cur=cur, provider=provider)
    assert first["judged"] >= 1 and second["judged"] == 0


# --------------------------------------------------------------------------- #
#  Agreement — the number that licenses handing over
# --------------------------------------------------------------------------- #
def test_agreement_counts_only_genuine_human_decisions(db_rollback):
    """352 of the 357 decided rows here are one bulk migration. Measuring the critic
    against them would be measuring it against a script."""
    cur = db_rollback.cursor()
    for reviewer in ("system:v2.0-migration", "auto:graduation"):
        cn, did = _awaiting(cur)
        cur.execute("update outreach.drafts set status='approved', decided_by=%s, "
                    "decided_at=now(), critic_verdict='pass', critic_score=90 "
                    "where id=%s", (reviewer, did))
    assert critic.agreement(cur)["compared"] == 0


def test_a_false_pass_is_reported_separately_from_a_false_fail(db_rollback):
    """The asymmetry is the point. A false PASS is a bad email sent; a false FAIL is a
    good email held for a human. Only the first is a reason not to hand over, and an
    averaged accuracy figure hides which way the errors fall."""
    cur = db_rollback.cursor()
    _, bad = _awaiting(cur)          # human REJECTED, critic passed → dangerous
    cur.execute("update outreach.drafts set status='rejected', decided_by='Finlay Salisbury', "
                "decided_at=now(), critic_verdict='pass', critic_score=90 where id=%s", (bad,))
    _, safe = _awaiting(cur)         # human APPROVED, critic failed → merely costly
    cur.execute("update outreach.drafts set status='approved', decided_by='Finlay Salisbury', "
                "decided_at=now(), critic_verdict='fail', critic_score=20 where id=%s", (safe,))

    out = critic.agreement(cur)
    assert out["false_pass"] >= 1 and out["false_fail"] >= 1
    assert out["ready_to_gate"] is False      # any false pass blocks the handover


# --------------------------------------------------------------------------- #
#  Calibration: measure agreement NOW, against the answer key
# --------------------------------------------------------------------------- #
def test_calibrate_judges_decided_drafts_without_disturbing_the_decision(db_rollback, critic_on):
    """Shadow mode otherwise measures agreement only against decisions made from now on —
    weeks before there is anything to judge it by. These rows already carry the answer."""
    cur = db_rollback.cursor()
    _, did = _awaiting(cur)
    cur.execute("update outreach.drafts set status='rejected', decided_by='Finlay Salisbury', "
                "decided_at=now(), reviewer_note='wrong location' where id=%s", (did,))

    provider = _FakeProvider({"score": 15, "verdict": "fail",
                              "reasons": [{"dimension": "grounding", "severity": "hard",
                                           "detail": "asserts a town not in FACTS"}]})
    out = critic.run(limit=50, cur=cur, provider=provider, calibrate=True)
    assert out["judged"] >= 1 and out["calibrate"] is True

    cur.execute("select status, decided_by, reviewer_note, critic_verdict "
                "from outreach.drafts where id=%s", (did,))
    status, by, note, verdict = cur.fetchone()
    assert (status, by, note) == ("rejected", "Finlay Salisbury", "wrong location")  # untouched
    assert verdict == "fail"                                                          # judged
    assert critic.agreement(cur)["compared"] >= 1


def test_calibrate_ignores_the_bulk_migration(db_rollback, critic_on):
    """352 of the 357 decided rows are one migration. Calibrating against a script
    measures nothing, and would burn a paid call per row doing it."""
    cur = db_rollback.cursor()
    _, did = _awaiting(cur)
    cur.execute("update outreach.drafts set status='rejected', "
                "decided_by='system:v2.0-migration', decided_at=now() where id=%s", (did,))
    critic.run(limit=50, cur=cur, calibrate=True,
               provider=_FakeProvider({"score": 90, "verdict": "pass", "reasons": []}))
    # asserts about THIS row only — the shared database holds real human decisions that
    # calibration legitimately picks up, and a global count would be describing those
    cur.execute("select critic_verdict from outreach.drafts where id=%s", (did,))
    assert cur.fetchone()[0] is None


def test_calibrate_does_not_touch_the_live_queue(db_rollback, critic_on):
    """The two backlogs are disjoint: calibration must not consume the drafts you are
    about to review, or shadow mode has nothing left to shadow."""
    cur = db_rollback.cursor()
    _, waiting = _awaiting(cur)
    critic.run(limit=50, cur=cur, calibrate=True,
               provider=_FakeProvider({"score": 90, "verdict": "pass", "reasons": []}))
    cur.execute("select critic_verdict from outreach.drafts where id=%s", (waiting,))
    assert cur.fetchone()[0] is None


def test_a_sent_draft_counts_as_a_human_approval(db_rollback):
    """Counting only status='approved' left 17 of this database's 21 human decisions
    invisible, and every survivor was a rejection. An answer key of rejections alone
    cannot detect the opposite failure: a critic that fails EVERYTHING scores 100%."""
    cur = db_rollback.cursor()
    _, did = _awaiting(cur)
    cur.execute("update outreach.drafts set status='sent', decided_by='Finlay Salisbury', "
                "decided_at=now(), critic_verdict='pass', critic_score=90 where id=%s", (did,))
    out = critic.agreement(cur)
    assert out["human_approvals"] >= 1


def test_a_lopsided_answer_key_is_not_ready_to_gate(db_rollback):
    """Enough comparisons and zero false passes is not sufficient — if they are all
    rejections the critic has never been shown a draft it should let through."""
    cur = db_rollback.cursor()
    for _ in range(40):
        _, did = _awaiting(cur)
        cur.execute("update outreach.drafts set status='rejected', "
                    "decided_by='Finlay Salisbury', decided_at=now(), "
                    "critic_verdict='fail', critic_score=10 where id=%s", (did,))
    out = critic.agreement(cur)
    assert out["false_pass"] == 0 and out["compared"] >= 40
    assert out["ready_to_gate"] is False, "a rejections-only sample proves nothing"
