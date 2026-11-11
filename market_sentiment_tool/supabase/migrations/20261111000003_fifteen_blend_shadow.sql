-- The self-weighting blend shadow for the 15-minute trade rule
-- (preregistration docs/superpowers/specs/2026-11-11-fifteen-blend-shadow-prereg.md,
-- frozen 2026-11-11): the blend's own decision rows (gate_version
-- 'v2-blend-shadow') for all six 15-minute series, the per-series daily
-- earned weights it gates on, the daily evaluation trail, and its own
-- promotion audit/state log. Its own tables on purpose: the oil shadow's
-- current_state reads the newest row of fifteen_promotions, so a blend
-- promotion row there would corrupt the oil gate's state. Written by
-- tradehub/scripts/fifteen_min_run.py (via tradehub/fifteen_blend.py);
-- read by /api/oil/fifteen-rule.
create table if not exists public.fifteen_blend_decisions (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  ticker text,
  window_open timestamptz,
  close_time timestamptz,
  frozen_at timestamptz,
  session text,
  gate_version text not null,
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
create index if not exists fifteen_blend_decisions_close_idx
  on public.fifteen_blend_decisions (series, close_time);
alter table public.fifteen_blend_decisions enable row level security;
revoke all on public.fifteen_blend_decisions from anon, authenticated;

create table if not exists public.fifteen_blend_weights (
  id bigint generated always as identity primary key,
  series text not null,
  day date not null,
  weight real not null,
  raw_slope real,
  n_contested int not null default 0,
  computed_at timestamptz not null,
  unique (series, day)
);
alter table public.fifteen_blend_weights enable row level security;
revoke all on public.fifteen_blend_weights from anon, authenticated;

create table if not exists public.fifteen_blend_evals (
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
  promoted boolean not null default false
);
alter table public.fifteen_blend_evals enable row level security;
revoke all on public.fifteen_blend_evals from anon, authenticated;

create table if not exists public.fifteen_blend_promotions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null,
  kind text not null,
  from_version text not null,
  to_version text not null,
  evidence jsonb
);
alter table public.fifteen_blend_promotions enable row level security;
revoke all on public.fifteen_blend_promotions from anon, authenticated;
