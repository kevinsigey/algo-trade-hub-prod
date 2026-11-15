-- The Binance-tape gold shadow (preregistration
-- docs/superpowers/specs/2026-11-14-fifteen-binance-gold-shadow-prereg.md,
-- frozen 2026-11-14): its own decision rows (gate_version
-- 'v5-binance-gold-shadow') for the gold 15-minute series only -- the same
-- model read at v1's freeze instant off the Binance XAUUSDT 1-minute tape
-- instead of Hyperliquid's, through the live rule's own evaluate -- and the
-- daily evaluation trail. No promotions table: the shadow records whether
-- its bar is met, and promotion is a separate commission on Kevin's word.
-- Written by tradehub/scripts/fifteen_min_run.py (via
-- tradehub/fifteen_binance.py); read from the tables until a surface is
-- commissioned.
create table if not exists public.fifteen_binance_decisions (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  ticker text,
  window_open timestamptz,
  close_time timestamptz,
  frozen_at timestamptz,
  session text,
  gate_version text not null,
  sigma_1m double precision,
  model_prob real,
  market_prob real,
  v1_prob real,
  action text not null,
  reason text,
  side text,
  cost real,
  edge_net real,
  best_edge_net real,
  outcome int,
  pnl real,
  evaluated_at timestamptz not null,
  unique (series, target)
);
create index if not exists fifteen_binance_decisions_close_idx
  on public.fifteen_binance_decisions (series, close_time);
create index if not exists fifteen_binance_decisions_open_idx
  on public.fifteen_binance_decisions (window_open);
alter table public.fifteen_binance_decisions enable row level security;
revoke all on public.fifteen_binance_decisions from anon, authenticated;

create table if not exists public.fifteen_binance_evals (
  id bigint generated always as identity primary key,
  evaluated_at timestamptz not null,
  windows int not null default 0,
  trades int not null default 0,
  net_per_contract real,
  low95 real,
  low95_clustered real,
  paired_windows int not null default 0,
  paired_delta real,
  paired_low95 real,
  paired_low95_clustered real,
  criterion_met boolean not null default false,
  eligible boolean not null default false
);
alter table public.fifteen_binance_evals enable row level security;
revoke all on public.fifteen_binance_evals from anon, authenticated;
