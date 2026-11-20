-- The would-have-filled record (Kevin's ruling via Claude, 2026-11-17):
-- at each Kalshi demo decision the runner also reads the PRODUCTION
-- book (public API, GET only, no credentials) and records what the
-- real book would have done with the same decision -- the frozen
-- quote, the production bid/ask, the contracts on offer at the bought
-- side's ask, the would-have price under the same cross rule, edge
-- bar and slippage cap as the demo cross, and the settled P&L once
-- the outcome lands. Observation only: no order path reads or writes
-- this table, and nothing here can place anything anywhere.
-- One row per (series, target, gate_version): the first observation
-- stands. Written and read by tradehub/kalshi_demo.py.
create table if not exists public.kalshi_prod_paper_fills (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  gate_version text not null,
  ticker text not null,
  side text not null,
  model_prob double precision,
  frozen_quote double precision,
  prod_yes_bid double precision,
  prod_yes_ask double precision,
  prod_no_bid double precision,
  prod_no_ask double precision,
  ask_size integer,
  would_price double precision,
  contracts integer,
  status text not null,
  outcome integer,
  pnl double precision,
  window_close timestamptz,
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  unique (series, target, gate_version)
);

alter table public.kalshi_prod_paper_fills enable row level security;
revoke all on public.kalshi_prod_paper_fills from anon, authenticated;
grant select, insert, update, delete on public.kalshi_prod_paper_fills to service_role;
