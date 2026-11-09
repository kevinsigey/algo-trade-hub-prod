-- The 15-minute trade rule's persisted tracking (amendment 2026-11-08): one gated decision per
-- targeted window (buys and named skips alike) and a per-minute-offset shadow track per settled
-- window, so the best entry minute can be read off data. Written by tradehub/scripts/fifteen_min_run.py
-- (via tradehub/fifteen_tracking.py) with the service role; read by /api/oil/fifteen-rule.
create table if not exists public.fifteen_rule_decisions (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  ticker text,
  window_open timestamptz,
  close_time timestamptz,
  frozen_at timestamptz,
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
  unique (series, target)
);
create index if not exists fifteen_rule_decisions_close_idx
  on public.fifteen_rule_decisions (series, close_time);
alter table public.fifteen_rule_decisions enable row level security;
revoke all on public.fifteen_rule_decisions from anon, authenticated;

create table if not exists public.fifteen_window_offsets (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  ticker text,
  close_time timestamptz,
  offset_min int not null,
  prob_up real,
  prob_source text,
  yes_bid real,
  yes_ask real,
  price double precision,
  side text,
  side_cost real,
  edge_net real,
  outcome int,
  pnl real,
  price_at_settle double precision,
  price_at_60m double precision,
  move_to_settle_bps double precision,
  move_to_60m_bps double precision,
  unique (series, target, offset_min)
);
create index if not exists fifteen_window_offsets_close_idx
  on public.fifteen_window_offsets (series, close_time);
alter table public.fifteen_window_offsets enable row level security;
revoke all on public.fifteen_window_offsets from anon, authenticated;
