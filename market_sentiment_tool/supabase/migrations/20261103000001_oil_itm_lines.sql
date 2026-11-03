-- Oil ITM line picks (Kevin, 2026-11-03): one frozen pick per hourly WTI
-- event -- the strike where our probability sat a bit over 50%, above
-- Kalshi's, with the tape clear of it for the trailing minutes. Graded
-- against the event's Kalshi settlement value; ev prices the bet at the
-- frozen market probability, per $1 at the mid. A calibration record,
-- never a trading signal.
create table if not exists public.oil_itm_lines (
  id bigint generated always as identity primary key,
  event_ticker text not null unique,
  strike numeric not null,
  ours numeric not null,
  market numeric not null,
  live_price numeric,
  frozen_at timestamptz not null default now(),
  settled boolean not null default false,
  hit boolean,
  ev numeric,
  settled_value numeric,
  settled_at timestamptz
);

alter table public.oil_itm_lines enable row level security;
