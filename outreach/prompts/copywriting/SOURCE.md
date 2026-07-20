# Vendored copywriting reference — provenance and sync

These files are **copies**, vendored deliberately. They are compiled into the drafting
prompt by `draft.load_playbook()` and must ship inside the Cloud Run image.

**Upstream:** the `copywriting` skill, installed at `~/.claude/skills/copywriting/`.

    references/platforms/cold-email-uk.md  -> cold-email-uk.md
    references/anti-patterns.md            -> anti-patterns.md

## Why vendored rather than referenced

`~/.claude/` does not exist in the container. A prompt that silently loses its craft
guidance in production — while still producing plausible-looking emails — is worse than
one that never had it, because nothing fails loudly. Vendoring makes the guidance a
git-tracked, reviewable, deployed artefact.

## Why only these two

Cost is not the reason (an implicit-cache probe on 2026-07-19 measured `cached=0` on
`gemini-3-flash-preview` via Vertex, so there is no prefix discount to chase today, and
the uncached cost is ~0.3p/draft on the GCP credit either way). The reason is **attention
dilution**: `mechanisms.md`, `frameworks.md` and `voice.md` are reasoning material for a
human choosing an approach. We have already made those choices — the framework, the
register and the voice are fixed and baked into `draft_email.md`. Feeding a 100-word
email a 12k-token brief buys nothing and costs focus.

## Sync policy

These are inputs to a *versioned* prompt. If you update either file, bump
`PLAYBOOK VERSION` in `../draft_email.md` — graduation metrics are windowed per
prompt_version, and changing the craft guidance changes the copy, so the new copy must
not inherit the old version's auto-send trust.
