-- Self-improving loop piece 1 (Kevin, 2026-11-03): the weekly critic's record.
-- One row per (idea, book) per week, append-only: the payload carries the
-- live-vs-backtest comparison in the claim's own units, the conditions losing
-- entries clustered in, the flags, and the PAUSE / HOLD / WATCH recommendation.
-- The critic only recommends; nothing in this table changes an idea's state.
create table if not exists public.idea_critiques (
  id bigint generated always as identity primary key,
  idea_id bigint not null,
  book text not null default 'main',
  at timestamptz not null default now(),
  payload jsonb not null
);

create index if not exists idea_critiques_idea_at
  on public.idea_critiques (idea_id, book, at desc);

alter table public.idea_critiques enable row level security;
