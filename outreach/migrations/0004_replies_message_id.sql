-- outreach-build · migration 0004 — inbound ingestion dedupe
-- A unique provider message id so reply/bounce/unsubscribe ingestion is idempotent
-- (re-reading the mailbox never double-suppresses or double-counts). Idempotent.

alter table outreach.replies add column if not exists message_id text;
create unique index if not exists replies_message_id_uidx
  on outreach.replies(message_id) where message_id is not null;
