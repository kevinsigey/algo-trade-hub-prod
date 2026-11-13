-- fifteen_replay_offsets: the Step A0 history replay's table (plan
-- docs/plan-2026-11-12-fifteen-rule-v4.md), shaped like
-- fifteen_window_offsets plus the replay's own fields.
--
-- NOT APPLIED. This ships in the Step A0 PR for Kevin's go through Claude,
-- per the plan's migration rule. Until it is applied, the backfill writes
-- JSONL under /cache/research/ and the Step A study reads that.
-- When approved: apply, then record the row in
-- docs/superpowers/plans/migrations-applied.md in the same PR that loads it.

create table if not exists public.fifteen_replay_offsets (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  ticker text,
  close_time timestamptz,
  offset_min int not null,
  prob_up double precision,
  prob_source text,
  source text not null default 'replay',
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
  candle_volume double precision,
  spread real,
  fillable boolean not null default false,
  unique (series, target, offset_min)
);
create index if not exists fifteen_replay_offsets_close_idx
  on public.fifteen_replay_offsets (series, close_time);
alter table public.fifteen_replay_offsets enable row level security;
revoke all on public.fifteen_replay_offsets from anon, authenticated;
