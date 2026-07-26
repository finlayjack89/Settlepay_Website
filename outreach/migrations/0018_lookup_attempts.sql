-- 0018 — never pay twice for the same answer.
--
-- `enrichment.dm_attempted_at` marks a LEAD as done. That is the wrong key for a paid
-- lookup, because the thing we buy is not "a lead" — it is "does <name> exist at
-- <domain>". Two leads can legitimately share a domain (a group, a franchise, the same
-- business discovered twice through Places and Companies House), and each one re-bills the
-- verifier for a question we already have the answer to.
--
-- Keyed on (provider, first, last, domain) so the cache survives re-enrichment, a lead
-- being re-keyed, and the same person appearing at two companies.
--
-- Negative results are the valuable half. A hit is already recorded on the enrichment row;
-- a MISS is otherwise invisible, and a miss is exactly what we would pay to rediscover.
-- Anymail Finder and Tomba make repeat searches free for 30 days; this mirrors that
-- server-side for every provider, with a longer window because a mailbox that did not
-- exist 90 days ago is very unlikely to have appeared under the same guessed pattern.

create table if not exists outreach.lookup_attempts (
  provider    text not null,              -- 'millionverifier' | 'reoon' | ... | 'chain'
  first_name  text not null,
  last_name   text not null,
  domain      text not null,
  outcome     text not null,              -- 'hit' | 'miss' | 'catch_all'
  address     text,                       -- the address tried (null when not applicable)
  created_at  timestamptz not null default now(),
  primary key (provider, first_name, last_name, domain)
);

create index if not exists lookup_attempts_recent_idx
  on outreach.lookup_attempts (created_at);

comment on table outreach.lookup_attempts is
  'Negative cache for paid decision-maker lookups. Keyed on the QUESTION (who, where, which provider), not on the lead — two leads can share a domain and would otherwise each be billed for the same answer.';
