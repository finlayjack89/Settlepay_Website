-- outreach-build · migration 0002 — phase G: per-inbox daily cap needs the
-- sending mailbox recorded on each send. Idempotent.
alter table outreach.sends add column if not exists from_inbox text;
create index if not exists sends_inbox_idx on outreach.sends (from_inbox);
