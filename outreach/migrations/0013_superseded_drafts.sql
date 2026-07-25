-- outreach-build · migration 0013 — a draft can be SUPERSEDED
--
-- Re-drafting a lead under a newer playbook needs somewhere for the old copy to go. The
-- options were: delete it (destroys the record of what was previously in the approval
-- queue), leave it (two live drafts for one lead, and the reviewer approves whichever
-- they happen to click), or retire it explicitly. Only the third is honest.
--
-- 'superseded' means: this was a real draft, it was never approved or sent, and a newer
-- one replaced it. It drops out of every queue automatically because those all filter on
-- status = 'awaiting_approval', while body_original stays immutable and auditable — so
-- the prompt_version comparison that drove the re-draft remains checkable afterwards.
--
-- Only awaiting_approval drafts are ever superseded. An approved or sent draft is a
-- decision (or a record of one) and re-writing it would be rewriting history.

alter table outreach.drafts drop constraint if exists drafts_status_check;
alter table outreach.drafts add constraint drafts_status_check
  check (status in ('awaiting_approval','approved','rejected','sent','superseded'));
