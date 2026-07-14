-- Extend public.bookings for the bespoke Google-Calendar booking flow.
--
-- Additive + idempotent. Does NOT change the status enum, the columns the ops
-- console reads, or the cal-webhook onConflict(cal_uid) path. The set_updated_at()
-- trigger (owned by the leads migration) is untouched.

-- (a) Google-Calendar bookings have no Cal.com uid.
--     (UNIQUE still holds for Cal rows; Postgres treats multiple NULLs as distinct.)
alter table public.bookings alter column cal_uid drop not null;

-- (b) Provenance + Google linkage + self-service manage capability.
alter table public.bookings add column if not exists source           text not null default 'cal';
alter table public.bookings add column if not exists google_event_id  text;
alter table public.bookings add column if not exists manage_token      uuid not null default gen_random_uuid();

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'bookings_source_chk') then
    alter table public.bookings add constraint bookings_source_chk check (source in ('cal', 'google'));
  end if;
end $$;

create unique index if not exists bookings_manage_token_uidx on public.bookings (manage_token);
create index        if not exists bookings_google_event_idx  on public.bookings (google_event_id);

-- (c) Double-booking backstop: at most one ACTIVE booking per start instant.
--     Partial so cancelled rows free the slot. Fixed 30-min grid means an equal
--     start_at is the same slot. This index is also the atomic lock the `book`
--     function relies on (insert → 23505 on a taken slot).
create unique index if not exists bookings_active_start_uidx
  on public.bookings (start_at) where status in ('confirmed', 'rescheduled');

comment on column public.bookings.source is 'Origin: cal (Cal.com webhook) | google (bespoke Google Calendar flow)';
comment on column public.bookings.manage_token is 'Unguessable token for the attendee reschedule/cancel link';
