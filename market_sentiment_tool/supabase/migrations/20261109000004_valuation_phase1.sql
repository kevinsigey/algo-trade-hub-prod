-- Valuation bands Phase 1: the forked debate's verdict record, its relative
-- grades, the band watch's memory, and the debate trigger queue.
--
-- valuation_verdicts is append-only: every render (and every void, where the
-- structured packet failed validation against the fact sheet) is a row. It
-- carries the verdict, the JUDGE identity, BOTH grading controls (the
-- band-rule baseline and the proposer's own pick), the peer state frozen at
-- render, and the options-layer inputs — grading joins exactly what the
-- verdict saw. Display-only: no idea, book, or order table reads this.
create table if not exists valuation_verdicts (
  id bigint generated always as identity primary key,
  ticker text not null,
  rendered_at timestamptz not null default now(),
  trigger text not null check (trigger in ('on_demand', 'crossing',
    'falsifier_window', 'new_guidance', 'refresh')),
  status text not null check (status in ('rendered', 'void')),
  void_reason text,
  judge text,
  proposer_model text,
  fact_sheet_id bigint,
  fact_sheet_computed_at timestamptz,
  price numeric,
  price_as_of date,
  bands jsonb,
  band_basis text,
  baseline_verdict text,
  verdict jsonb,
  proposer_pick jsonb,
  choices jsonb,
  rubric_weights jsonb,
  digest text,
  bull_case text,
  bear_case text,
  options_inputs jsonb,
  frozen_peers jsonb,
  falsifier text,
  entry_price numeric,
  target_price numeric,
  debate_run_id text
);

create index if not exists valuation_verdicts_ticker_idx
  on valuation_verdicts(ticker, rendered_at desc);

alter table valuation_verdicts enable row level security;

-- One row per verdict x horizon (+20/+60 trading days), upserted by the
-- grading job. The verdict's own relative grade is primary; both controls
-- are graded on the same frozen context beside it.
create table if not exists valuation_verdict_grades (
  id bigint generated always as identity primary key,
  verdict_id bigint not null references valuation_verdicts(id)
    on delete cascade,
  horizon int not null check (horizon in (20, 60)),
  verdict_relative_pass boolean,
  verdict_brier numeric,
  baseline_relative_pass boolean,
  baseline_brier numeric,
  proposer_relative_pass boolean,
  proposer_brier numeric,
  name_ret_pct numeric,
  peer_median_ret_pct numeric,
  peer_excess_pct numeric,
  peers_graded int,
  index_excess_pct numeric,
  basket_ret_pct numeric,
  mfe_pct numeric,
  mae_pct numeric,
  time_to_target_days int,
  graded_at timestamptz not null default now(),
  unique (verdict_id, horizon)
);

create index if not exists valuation_verdict_grades_verdict_idx
  on valuation_verdict_grades(verdict_id);

alter table valuation_verdict_grades enable row level security;

-- The band watch's memory: one row per watched thing (held:<book>:<symbol>
-- for position flags, ticker:<TICKER> for crossing/guidance detection).
create table if not exists valuation_watch_state (
  key text primary key,
  kind text not null check (kind in ('held', 'ticker')),
  ticker text,
  zone text,
  price numeric,
  last_guide_at timestamptz,
  state jsonb,
  updated_at timestamptz not null default now()
);

alter table valuation_watch_state enable row level security;

-- The debate queue: event triggers wait here and drain by priority
-- (crossings/falsifier windows 1, new guidance 2, refresh 3).
create table if not exists valuation_triggers (
  id bigint generated always as identity primary key,
  ticker text not null,
  kind text not null check (kind in ('crossing', 'falsifier_window',
    'new_guidance', 'refresh')),
  priority int not null,
  state text not null default 'pending'
    check (state in ('pending', 'done', 'failed')),
  detail jsonb,
  verdict_id bigint references valuation_verdicts(id),
  created_at timestamptz not null default now()
);

create index if not exists valuation_triggers_pending_idx
  on valuation_triggers(state, priority, created_at);

alter table valuation_triggers enable row level security;
