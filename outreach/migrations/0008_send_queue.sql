-- 0008_send_queue.sql — per-draft send scheduling.
--
-- Approval used to mean "send on the next tick", and _advance_sends fired every
-- approved draft in one loop. At 5/day that was invisible; at the 50/day ceiling it
-- would put 50 cold emails on the wire within seconds, which is exactly the burst
-- pattern Google's bulk-sender guidance says to avoid ("send email at a consistent
-- rate; avoid sending email in bursts").
--
-- Approving a draft now assigns it a slot: a specific minute inside the send window
-- on the first day with capacity left. Overflow rolls to the next send day. The send
-- stage only picks up drafts whose slot has arrived, so pacing is a property of the
-- queue rather than something the tick has to reason about.
alter table outreach.drafts add column if not exists scheduled_at timestamptz;

-- the send stage's hot path: due, approved, not yet sent
create index if not exists drafts_scheduled_at_idx
  on outreach.drafts (scheduled_at)
  where status = 'approved';
