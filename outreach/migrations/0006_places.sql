-- 0006_places.sql — Places-sourced local ICP discovery + the corporate cross-reference.
-- Places businesses arrive WITHOUT a Companies House number; the cross-reference matches
-- them to a registered company to set subscriber_class (the PECR send-legality gate).
-- Sole-trader / unmatched leads are KEPT (research-only) for market intelligence, a
-- re-incorporation watch, and future consent/postal channels — never electronic cold mail.

-- Places identity + dedup (company_number stays the stable synthetic id 'PLACE:<place_id>').
alter table outreach.leads add column if not exists place_id text;
create unique index if not exists leads_place_id_idx
  on outreach.leads(place_id) where place_id is not null;

-- The Companies House number the cross-reference matched (null until/unless matched).
alter table outreach.leads add column if not exists matched_company_number text;

-- When the cross-reference last ran (for the re-incorporation watch on research-only leads).
alter table outreach.leads add column if not exists crossref_checked_at timestamptz;
