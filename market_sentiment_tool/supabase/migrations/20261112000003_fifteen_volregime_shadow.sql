-- The volatility-regime challenger to the 15-minute blend
-- (preregistration docs/superpowers/specs/2026-11-13-fifteen-volregime-shadow-prereg.md,
-- frozen 2026-11-13): its own decision rows (gate_version
-- 'v3-volregime-shadow') for all six 15-minute series, the per-series,
-- per-regime daily weights with the trailing median they split on, and the
-- daily evaluation trail. No promotions table: the challenger has no
-- promotion path until the blend is promoted. Written by
-- tradehub/scripts/fifteen_min_run.py (via tradehub/fifteen_volregime.py);
-- read by /api/oil/fifteen-rule.
create table if not exists public.fifteen_volregime_decisions (
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
  median_sigma double precision,
  regime text,
  weight real,
  model_prob real,
  market_prob real,
  blend_prob real,
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
create index if not exists fifteen_volregime_decisions_close_idx
  on public.fifteen_volregime_decisions (series, close_time);
create index if not exists fifteen_volregime_decisions_open_idx
  on public.fifteen_volregime_decisions (window_open);
alter table public.fifteen_volregime_decisions enable row level security;
revoke all on public.fifteen_volregime_decisions from anon, authenticated;

create table if not exists public.fifteen_volregime_weights (
  id bigint generated always as identity primary key,
  series text not null,
  day date not null,
  regime text not null check (regime in ('low', 'high')),
  median_sigma double precision,
  weight real not null,
  raw_slope real,
  n_contested int not null default 0,
  computed_at timestamptz not null,
  unique (series, day, regime)
);
alter table public.fifteen_volregime_weights enable row level security;
revoke all on public.fifteen_volregime_weights from anon, authenticated;

create table if not exists public.fifteen_volregime_evals (
  id bigint generated always as identity primary key,
  evaluated_at timestamptz not null,
  windows int not null default 0,
  trades int not null default 0,
  net_per_contract real,
  low95 real,
  paired_windows int not null default 0,
  paired_delta real,
  paired_low95 real,
  criterion_met boolean not null default false,
  blend_promoted boolean not null default false,
  eligible boolean not null default false
);
alter table public.fifteen_volregime_evals enable row level security;
revoke all on public.fifteen_volregime_evals from anon, authenticated;
