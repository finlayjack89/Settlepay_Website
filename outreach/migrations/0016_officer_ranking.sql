-- 0016 — rank the officers, so we spend on the RIGHT person.
--
-- `get_officers` ordered by `appointed_on nulls last` and `resolve_one` took the first —
-- i.e. longest-serving wins. That is one signal used alone, and on a company with three
-- directors it picks the founder's retired co-director as often as the owner-operator.
-- Every downstream cost (a verifier credit, a draft, an actual email to a human) is spent
-- on whoever that ordering happened to surface.
--
-- The strongest available signal is PSC — a person with significant control. Someone who
-- is BOTH an active director AND a significant shareholder is, for an owner-managed UK
-- SME, almost always the buyer. It is a free Companies House call and we were not making
-- it.
--
-- MINIMISATION (continuing the 0011 doctrine, UK GDPR art. 5(1)(c)):
-- the PSC endpoint returns natures_of_control (ownership bands), a correspondence address,
-- a partial DOB and nationality. We store NONE of it. We store a single BOOLEAN — "is this
-- officer also a person with significant control" — because the question we need answered
-- is "is this the owner", not "how much do they own". The name elements are read in memory
-- to match PSC to officer and then discarded.
--
-- `occupation` IS kept: it is role information about their position at the company (the
-- same category as officer_role, which 0011 already keeps), it is a ranking signal the
-- register gives away free ("Managing Director", "Auctioneer"), and it is exactly the
-- context that makes a legitimate-interests case for contacting someone in that role.

alter table outreach.officers add column if not exists occupation text;
alter table outreach.officers add column if not exists is_psc     boolean not null default false;
alter table outreach.officers add column if not exists rank       int     not null default 0;

create index if not exists officers_rank_idx
  on outreach.officers (company_number, rank desc, appointed_on);

comment on column outreach.officers.is_psc is
  'Also an active individual PSC. A BOOLEAN on purpose: we never store natures_of_control, PSC address, DOB or nationality.';
comment on column outreach.officers.occupation is
  'Self-declared occupation from the register (e.g. "Managing Director") — a free ranking signal and the role context the LIA rests on.';
comment on column outreach.officers.rank is
  'Computed decision-maker score, higher is better. See decisionmakers.rank_officer.';
