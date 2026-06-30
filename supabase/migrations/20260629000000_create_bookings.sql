-- Migration: public.bookings — consultation bookings captured from Cal.com.
--
-- The cal-webhook Edge Function (service-role) upserts a row per Cal.com booking
-- (created / rescheduled / cancelled). The operations console reads this to show
-- the Schedule. No public/anon access — RLS on, no policies (service-role bypasses).
--
-- Provider-agnostic: Cal.com supplies the video join link (Cal Video, Zoom, Meet…),
-- so nothing here is tied to Microsoft/Teams.

create extension if not exists pgcrypto;

create table if not exists public.bookings (
  id                 uuid        primary key default gen_random_uuid(),
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  cal_uid            text        not null unique,   -- Cal.com booking uid (idempotency key)
  status             text        not null default 'confirmed'
                     check (status in ('confirmed','rescheduled','cancelled')),
  title              text,
  start_at           timestamptz not null,
  end_at             timestamptz,
  attendee_name      text,
  attendee_email     text,
  attendee_timezone  text,
  join_url           text,                           -- video link from Cal.com
  reminder_sent      boolean     not null default false,
  -- best-effort link to the originating enquiry (no FK: survives the planned
  -- public.leads -> public.enquiries rename).
  lead_id            uuid,
  raw                jsonb                           -- full Cal.com payload, for audit/replay
);

comment on table public.bookings is
  'Consultation bookings from Cal.com (via cal-webhook). Inbound scheduling side.';

create index if not exists bookings_start_at_idx on public.bookings (start_at);
create index if not exists bookings_status_idx   on public.bookings (status);
create index if not exists bookings_email_idx     on public.bookings (lower(attendee_email));

-- Reuse the shared updated_at trigger function (created by the leads migration).
drop trigger if exists bookings_set_updated_at on public.bookings;
create trigger bookings_set_updated_at
  before update on public.bookings
  for each row execute function public.set_updated_at();

alter table public.bookings enable row level security;
