-- The oil minute-1 x 0.05-bar shadow variant (preregistration
-- docs/superpowers/specs/2026-11-09-fifteen-shadow-oil-minute1-prereg.md):
-- the shadow's own decision rows over the offsets 1..5 x bars {0.05, 0.10}
-- grid (gate_version 'v2-oil-shadow'), the daily evaluation trail, and the
-- promotion audit/state log. The v1 decisions gain a gate_version stamp
-- ('v1' on every existing and future v1 row) so a promoted oil segment
-- ('v2-oil') stays separable in the data forever. Written by
-- tradehub/scripts/fifteen_min_run.py (via tradehub/fifteen_shadow.py and
-- tradehub/fifteen_tracking.py); read by /api/oil/fifteen-rule.
create table if not exists public.fifteen_shadow_decisions (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  ticker text,
  window_open timestamptz,
  close_time timestamptz,
  offset_min int not null,
  bar real not null,
  gate_version text not null,
  session text,
  action text not null,
  reason text,
  side text,
  cost real,
  model_prob real,
  edge_net real,
  best_edge_net real,
  outcome int,
  pnl real,
  evaluated_at timestamptz not null,
  unique (series, target, offset_min, bar)
);
create index if not exists fifteen_shadow_decisions_close_idx
  on public.fifteen_shadow_decisions (series, close_time);
alter table public.fifteen_shadow_decisions enable row level security;
revoke all on public.fifteen_shadow_decisions from anon, authenticated;

create table if not exists public.fifteen_shadow_evals (
  id bigint generated always as identity primary key,
  evaluated_at timestamptz not null,
  windows int not null default 0,
  trades int not null default 0,
  net_per_contract real,
  low95 real,
  paired_windows int not null default 0,
  paired_delta real,
  paired_low95 real,
  closed_windows int not null default 0,
  closed_delta real,
  closed_low95 real,
  criterion_met boolean not null default false,
  promoted boolean not null default false
);
alter table public.fifteen_shadow_evals enable row level security;
revoke all on public.fifteen_shadow_evals from anon, authenticated;

create table if not exists public.fifteen_promotions (
  id bigint generated always as identity primary key,
  created_at timestamptz not null,
  kind text not null,
  from_version text not null,
  to_version text not null,
  evidence jsonb
);
alter table public.fifteen_promotions enable row level security;
revoke all on public.fifteen_promotions from anon, authenticated;

alter table public.fifteen_rule_decisions
  add column if not exists gate_version text not null default 'v1';
