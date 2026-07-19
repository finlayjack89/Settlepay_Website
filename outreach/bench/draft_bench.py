"""Drafting bench — single-variable model bake-off on frozen ICP leads.

Compares candidate drafting models against the incumbent (claude-sonnet-4-6) using
the EXACT production draft path (draft.draft_one's prompt + check_envelope gate),
so the bench reflects what ships. Scores each draft on:
  - envelope: deterministic check_envelope violations (0 = compliant) — a HARD gate
  - words: length vs the <110 target
  - judged wins: a BLIND pairwise judge (claude-haiku-4-5, a different tier than the
    sonnet incumbent and a different family than the Gemini candidate) picks which of
    two anonymised drafts better fits the brief; A/B order alternates to fight position bias

Run on demand — it SPENDS (metered into outreach.spend). Not a pytest.

  .venv/bin/python bench/draft_bench.py
"""
from __future__ import annotations
import json
from pathlib import Path

from outreach import config  # noqa: F401  (loads .env / config side effects)
from outreach.draft import MAX_WORDS, check_envelope, load_playbook
from outreach.llm import get_provider

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "draft_leads.json"

# (label, provider-name, model) — baseline first; the pairwise is baseline vs each.
# Both generators are Gemini so the Claude judge is fully decorrelated (no same-family bias).
CANDIDATES = [
    ("gemini-3-flash", "gemini", "gemini-3-flash-preview"),
    ("gemini-3.5-flash", "gemini", "gemini-3.5-flash"),
]
JUDGE_MODEL = "claude-haiku-4-5"


def _draft(provider, playbook, lead) -> str:
    prompt = f"{playbook}\n\nCOMPANY: {lead['company_name']}\nSIGNAL: {lead['signal']}\n"
    return provider.complete(prompt, purpose="bench_draft", max_words=MAX_WORDS).text.strip()


def _judge(judge, brief, a, b) -> str:
    """Blind pairwise: returns 'A' or 'B'. The judge never sees authorship."""
    prompt = (
        "You are judging two cold outreach emails for the SAME small UK business. "
        "The better one: opens with a specific, human line about THAT business; is "
        "accurate (never claims they take cash if unknown); states payments are handled "
        "by FCA-regulated partners; has a single reply-based call to action, an "
        "unsubscribe line, and a clean sign-off; and reads as calm and credible, not "
        "salesy; and is SHORT and to the point — a busy owner reads it in seconds "
        "(well under 110 words). Do NOT reward extra length or detail; brevity is better.\n\n"
        f"BUSINESS BRIEF:\n{brief}\n\n=== EMAIL A ===\n{a}\n\n=== EMAIL B ===\n{b}\n\n"
        "Reply with exactly one character: A or B.")
    out = judge.complete(prompt, purpose="bench_judge").text.strip().upper()
    return "A" if out.startswith("A") else "B"


def main():
    leads = json.loads(FIXTURE.read_text())
    playbook = load_playbook()
    providers = {}
    for label, pname, model in CANDIDATES:
        try:
            providers[label] = get_provider(pname, model=model)
        except Exception as e:
            print(f"skip {label}: {e}")
    judge = get_provider("api", model=JUDGE_MODEL)

    # 1) generate + deterministic scores
    drafts: dict[str, list[str]] = {lbl: [] for lbl in providers}
    print(f"\n{'model':18} {'ok/envlp':9} {'avg words':9}")
    det = {}
    for lbl, prov in providers.items():
        texts, violations, words = [], 0, []
        for lead in leads:
            try:
                t = _draft(prov, playbook, lead)
            except Exception as e:
                t = f"(error: {e})"
            texts.append(t)
            v = check_envelope(t)
            violations += 1 if v else 0
            words.append(len(t.split()))
        drafts[lbl] = texts
        det[lbl] = {"clean": len(leads) - violations, "avg_words": round(sum(words)/len(words), 1)}
        print(f"{lbl:18} {det[lbl]['clean']}/{len(leads):<7} {det[lbl]['avg_words']}")

    # 2) blind pairwise: incumbent vs each challenger
    base = CANDIDATES[0][0]
    print(f"\nBlind pairwise vs incumbent ({base}), judge={JUDGE_MODEL}:")
    for lbl in providers:
        if lbl == base:
            continue
        wins = {base: 0, lbl: 0}
        for i, lead in enumerate(leads):
            a_is_base = (i % 2 == 0)   # alternate positions to fight bias
            a, b = (drafts[base][i], drafts[lbl][i]) if a_is_base else (drafts[lbl][i], drafts[base][i])
            pick = _judge(judge, lead["signal"], a, b)
            winner = (base if a_is_base else lbl) if pick == "A" else (lbl if a_is_base else base)
            wins[winner] += 1
        print(f"  {lbl:18} {wins[lbl]}  vs  {base} {wins[base]}   (of {len(leads)})")

    # 3) sample drafts for eyeballing
    print("\n--- sample drafts (lead 0) ---")
    for lbl in providers:
        print(f"\n[{lbl}]\n{drafts[lbl][0]}")


if __name__ == "__main__":
    main()
