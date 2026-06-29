# SettlePay — operations console (inbound side)

A localhost-only operator console for the **inbound** business: website enquiries
(`public.leads`) as a CRM, and — later — consultations/bookings.

It deliberately reuses the **outreach operator console's design system**
(`outreach/outreach/web.py`) — same Satoshi type, brand `#0F172A`, action `#3B82F6`,
sidebar shell, tiles/funnel/badges — so the two consoles fold into a single
operations surface later (the shared `_STYLE`/`_shell` should be DRY'd at that point).

> ⚠️ **No authentication. Localhost only — never expose publicly.** It can read and
> update lead status/notes directly.

## Run

```bash
cd console
cp .env.example .env            # fill DATABASE_URL (Supabase → Session pooler)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --port 8799
# open http://localhost:8799/
```

Without a `DATABASE_URL` the console still runs and renders the layout (empty
state) — useful for design work.

## Pages
- **Dashboard** — KPIs, pipeline distribution, latest enquiries.
- **Enquiries** — the CRM: filter by status, open a record.
- **Enquiry** — full message + manage status (`new → contacted → quoted →
  won/lost/client`) and private notes.
- **Schedule** — placeholder until Microsoft Bookings + Graph are connected
  (see `../Docs/BOOKING-CRM-PLAN.md`).
- **Settings** — data source + integration status (read-only).

## Data model
Reads/updates `public.leads` (see `../supabase/migrations/`). Status + notes
columns already exist for exactly this pipeline. The table is slated to be renamed
`public.leads → public.enquiries`; set `ENQUIRY_SOURCE_TABLE=enquiries` after that
lands (coordinate with the outreach pipeline, which suppresses against the same table).
