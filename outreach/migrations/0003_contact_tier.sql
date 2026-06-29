-- outreach-build · migration 0003 — contact tier (catch-all handling)
-- A verified ('ok') contact and a catch-all ('risky') contact are both reachable,
-- but the catch-all is unconfirmable and must be sent to more cautiously. Record the
-- tier so the UI flags it and send.py can gate it separately. Idempotent.

alter table outreach.enrichment add column if not exists contact_tier text;
create index if not exists enrichment_tier_idx on outreach.enrichment(contact_tier);
