-- 0017 — record whether a contact address was SOURCED or DERIVED.
--
-- These are not the same act, and UK commentary treats them very differently:
--
--   sourced  — the business published this address on its own site, or a provider
--              returned it. We are using a contact they chose to make public.
--   derived  — we combined a name from the public register with a pattern and confirmed
--              the result with a verifier. Nobody published it; we worked it out.
--
-- Both can be lawful under legitimate interests, but only the second is the practice that
-- has drawn ICO complaints in the UK, and it is the one a regulator would ask about
-- first. Storing which is which means we can answer that question per-address instead of
-- per-pipeline, and it gives a kill switch (SEND_DERIVED_ENABLED) that can refuse derived
-- addresses at the envelope without unpicking anything upstream.
--
-- Deliberately nullable: rows written before this column existed genuinely do not know,
-- and back-filling a guess would defeat the entire point of recording provenance.

alter table outreach.enrichment add column if not exists contact_method text;

comment on column outreach.enrichment.contact_method is
  'How we came by contact_email: ''sourced'' (published by the business / returned by a provider) or ''derived'' (inferred from a name + pattern, then verified). NULL = predates the column; never guessed.';
