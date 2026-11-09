-- Valuation bands Phase 0: deterministic fact sheets + bear/base/bull bands
-- computed from the recorded guidance file (valuation Spec v1, sections 1-2).
-- Append-only: every compute pass inserts a new row; the latest row per
-- ticker is the current sheet. Service role only; no anon or authenticated
-- access. Display data only -- no book, order, or debate hooks read this.
create table if not exists valuation_fact_sheets (
  id bigint generated always as identity primary key,
  ticker text not null,
  tier text not null default 'open' check (tier in ('watch', 'open')),
  status text not null check (status in ('banded', 'no_full_year_guide',
    'guide_rejected', 'no_peer_multiple')),
  price numeric,
  price_as_of date,
  peer_group text,
  peer_multiple numeric,
  peer_count int,
  peer_basis text,
  anchor jsonb,
  bands jsonb,
  implied_eps numeric,
  gap_range_widths numeric,
  guidance_percentile numeric,
  baseline_verdict text,
  stale boolean not null default false,
  falsifier text,
  directions jsonb,
  fundamentals jsonb,
  inputs jsonb,
  computed_at timestamptz not null default now()
);

create index if not exists valuation_fact_sheets_ticker_idx
  on valuation_fact_sheets(ticker, computed_at desc);

alter table valuation_fact_sheets enable row level security;
