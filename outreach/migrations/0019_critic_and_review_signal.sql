-- outreach-build · migration 0019 — the critic's verdict, and reviewer notes as DATA
--
-- Two halves of the same problem: nothing in this system has ever learned from a review.
--
-- (a) THE CRITIC. An independent model reads each draft against its own facts block and
--     records a verdict. It starts in SHADOW mode — it scores and stores, and changes
--     nothing — so its agreement with real human decisions can be MEASURED before it is
--     trusted with any of them. Storing the verdict on the draft (rather than in a side
--     table) is deliberate: the draft is what was judged, and a verdict that can drift
--     away from the text it describes is worthless.
--
-- (b) REVIEWER NOTES. reviewer_note has existed since 0001 and has never been read by
--     anything. Five notes exist, and every substantive one names a FACTS error, not a
--     prose error:
--
--       "Brand name is yellowstone, not yellow. Not london based but email says london"
--       "wrong location"
--       "US-bAsed"
--       "Lead email doesn't match the company or terminology in the email."
--
--     That is a complete indictment of the enrichment stage and an acquittal of the
--     drafter — and it was sitting in a text column nobody aggregated. Classifying the
--     note gives the signal a stage to be routed to, so "the reviewer rejected this" can
--     become "enrichment resolved the wrong town, again".

alter table outreach.drafts add column if not exists critic_verdict text;
alter table outreach.drafts add column if not exists critic_score int;
alter table outreach.drafts add column if not exists critic_reasons jsonb;
alter table outreach.drafts add column if not exists critic_model text;
alter table outreach.drafts add column if not exists critic_at timestamptz;

alter table outreach.drafts drop constraint if exists drafts_critic_verdict_check;
alter table outreach.drafts add constraint drafts_critic_verdict_check
  check (critic_verdict is null or critic_verdict in ('pass', 'fail', 'error'));

comment on column outreach.drafts.critic_verdict is
  '''pass''/''fail'' from the independent critic, or ''error'' when the critic could not '
  'be reached. NULL = not yet judged. In shadow mode this column is written and never read '
  'by any gate — that is the point.';

-- The stage a rejection is really ABOUT. Deliberately small and closed: a category list
-- that grows per-reviewer stops being aggregatable, which is how reviewer_note ended up
-- unread in the first place.
--   facts_wrong      a constant was wrong (location, company/brand name, established…)
--   wrong_recipient  the address does not belong to this business
--   not_icp          a real business, but not one we should be writing to at all
--   copy             the prose itself — tone, length, claim, structure
--   other            genuinely none of the above (kept so nothing is forced into a lie)
alter table outreach.drafts add column if not exists note_category text;
alter table outreach.drafts drop constraint if exists drafts_note_category_check;
alter table outreach.drafts add constraint drafts_note_category_check
  check (note_category is null or note_category in
         ('facts_wrong', 'wrong_recipient', 'not_icp', 'copy', 'other'));

-- Which stage owns the fix. Derived from the category, stored rather than computed so a
-- later change to the mapping cannot silently rewrite history.
alter table outreach.drafts add column if not exists note_stage text;

create index if not exists drafts_note_category_idx
  on outreach.drafts(note_category) where note_category is not null;
create index if not exists drafts_critic_idx
  on outreach.drafts(critic_verdict) where critic_verdict is not null;
