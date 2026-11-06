-- The 15-minute markets' live read once a minute (Kevin, 2026-11-05): the model's chance and Kalshi's quotes
-- through each window, so a "first time the edge clears the bar" rule can be tested against the minute-5 freeze.
-- Written by tradehub/scripts/fifteen_min_tape.py with the service role; nothing public reads it directly.
create table if not exists public.fifteen_min_ticks (
  id bigint generated always as identity primary key,
  at timestamptz not null,
  series text not null,
  ticker text,
  close_time timestamptz,
  elapsed_min real,
  prob_up real,
  yes_bid real,
  yes_ask real,
  price double precision,
  open_price double precision
);
create index if not exists fifteen_min_ticks_close_idx on public.fifteen_min_ticks (series, close_time);
alter table public.fifteen_min_ticks enable row level security;
revoke all on public.fifteen_min_ticks from anon, authenticated;
