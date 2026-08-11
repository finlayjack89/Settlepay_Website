# LLM Model Registry — SettlePay outreach

> Verified live on **Vertex AI (project settlepay-502417, global endpoint) 2026-07-19**.
> Do NOT "correct" these identifiers from training memory — post-cutoff strings look
> wrong and are usually right. Cross-check live provider docs before changing any
> string, and update this file in the same change. Project file overrides the
> account master (~/.claude/LLM_MODELS.md) for this project; code constants
> (outreach/config.py) override both for what actually runs.

## Role assignments
| Pipeline role | Class | Bound model | Config | Why |
|---|---|---|---|---|
| Enrichment signal + ICP-fit gate | fast extraction | `gemini-3.1-flash-lite` | thinking_budget=0, JSON schema | highest volume, mechanical, cheapest; billed to GCP credit |
| Draft / follow-up | workhorse generation | **`gemini-3-flash-preview`** (LLM_PROVIDER=gemini) | thinking_budget=0 | won the Gemini bench 4–2 AND 3× cheaper than 3.5-flash; on the credit |
| Draft — fallback | workhorse | `claude-sonnet-4-6` (LLM_PROVIDER=api) | max_tokens=1024 | one env var away if ever needed |
| **Draft critic** | independent judge | **`gpt-5.6-luna`** (CRITIC_PROVIDER=openai) | reasoning_effort=low, max_completion_tokens>=2000 | MUST NOT be the drafter's family — see below |

### Drafting bench (2026-07-19, 6 frozen ICP leads, judge=claude-haiku-4-5, bench/draft_bench.py)
Round 1 — Gemini vs the Claude incumbent (judge not told the word limit → length bias):
sonnet won the blind judge 6–0 over gemini-3-flash but overshot the 125-word cap 5/6;
gemini-3-flash was most compliant (4/6). Confounded (same-family judge), so inconclusive
on prose.
Round 2 — **user's call: the two Gemini flash models head-to-head**, judge now told to
reward brevity (both generators Gemini → judge fully decorrelated):
| Model | $/1M (in/out) | Envelope-clean (1st pass) | Blind pairwise |
|---|---|---|---|
| **`gemini-3-flash-preview`** | 0.50/3.00 | 2/6 | **won 4–2** |
| `gemini-3.5-flash` | 1.50/9.00 | 1/6 | lost 2–4 |
**Decision: `gemini-3-flash-preview` for drafting** — it won the head-to-head AND is
3× cheaper. Both overshoot the word cap on first pass (~2/6 clean); draft_one's retry
recovers it. LLM_PROVIDER=gemini promoted 2026-07-19.
| Reply classification | — | none (deterministic regex) | — | works, free |

## Provider details
### Google Gemini (via Vertex AI — auth ADC / runtime SA, no key)
| Model | API ID | $/1M in | $/1M out | Thinking billing | Notes (verified live 2026-07-19) |
|---|---|---|---|---|---|
| Gemini 3 Flash | `gemini-3-flash-preview` | $0.50 | $3.00 | at OUTPUT rate | works on Vertex; **defaults thinking ON** (~112 tok on a trivial prompt) |
| Gemini 3.1 Flash-Lite | `gemini-3.1-flash-lite` | $0.25 | $1.50 | at OUTPUT rate | works on Vertex; JSON schema output verified |
| Gemini 3.5 Flash | `gemini-3.5-flash` | $1.50 | $9.00 | at OUTPUT rate | not bound; fallback if Flash hallucinates |

- **Disable thinking with `thinking_config.thinking_budget=0`** — `thinking_level="low"`
  still spent ~85 thinking tokens; only budget=0 zeroed it. Set per call in `GeminiProvider`.
- units_out passed to the cost function = `candidates_token_count + thoughts_token_count`
  (thinking billed at the output rate).
- Batch mode = −50% (24h turnaround); Vertex regional endpoints +10% from 2026-07-01
  → use `location=global`. Cached prefixes discounted (playbook prefix candidate).
- Quota/billing project = `settlepay-502417` (the GCP credit). Runtime SA
  `settlepay-ops-run@…` has `roles/aiplatform.user`.

### OpenAI (the critic — cash-billed, NOT the GCP credit)
| Model | API ID | $/1M in | $/1M out | Notes |
|---|---|---|---|---|
| GPT-5.6 Luna | `gpt-5.6-luna` | $1.00 | $6.00 | the draft critic; cheapest of the 5.6 tier |
| GPT-5.6 Terra | `gpt-5.6-terra` | $2.50 | $15.00 | not bound |
| GPT-5.6 Sol | `gpt-5.6-sol` | $5.00 | $30.00 | not bound |

**Why OpenAI at all, when Gemini is on the credit:** the critic's entire value is being
*decorrelated* from the drafter. A judge from the generator's own family shares its blind
spots — round 1 of the drafting bench had to be thrown out for exactly that reason. Paying
cash for a second opinion is the point; a free correlated one is worth less than nothing,
because it produces confident agreement that looks like evidence. `config.CRITIC_PROVIDER`
holds the split and `llm.critic_provider()` is deliberately separate from
`llm.draft_provider()` so the two cannot quietly converge.

- ⚠️ **`max_completion_tokens`, NOT `max_tokens`** — the reasoning family rejects the old name.
- ⚠️ **Reasoning is spent from that budget BEFORE any output**, so too small a number returns
  an EMPTY STRING rather than an error — i.e. a critic that silently passes everything.
  `OpenAIProvider.MIN_COMPLETION_TOKENS = 2000` is the floor, not a preference.
- ⚠️ **The bare `gpt-5.6` alias routes to Sol**, 5× Luna's price. Always name the tier.
- A critic call is ~2k in / ~1k out ≈ £0.006. At 10/tick this is noise against the £50 cap,
  but it is CASH — `spend.CASH_PROVIDERS` includes `openai` so the cap gate sees it.

### Anthropic (incumbent drafting champion)
| Model | API ID | $/1M in | $/1M out | Notes |
|---|---|---|---|---|
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | $3.00 | $15.00 | current draft/signal model; being benched against Gemini |

## Anti-patterns (known-wrong — never use)
- ❌ `gemini-3.1-flash` (404 on the live API — use `gemini-3-flash-preview`)
- ❌ `gemini-flash-lite-latest` (500 INTERNAL on Vertex 2026-07-19)
- ❌ `claude-sonnet-4.6` (Anthropic uses hyphens)
- ❌ `thinking_level="low"` when you mean OFF (still bills thinking — use budget=0)
