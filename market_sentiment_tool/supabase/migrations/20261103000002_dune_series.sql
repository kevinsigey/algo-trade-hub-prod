-- Dune series cache (crypto step 3, Kevin, 2026-11-03): Dune Analytics
-- query results cached as dated points, so Workshop rules can read
-- on-chain series the way they read FRED. The hub has no Dune key of
-- its own -- Kevin's Dune credential lives in his connector vault -- so
-- a refresh job on Muse's side runs his queries and upserts the points
-- here; the engine only ever reads this table. One row per series key.
create table if not exists public.dune_series (
  key text primary key,
  query_id bigint not null,
  value_column text not null,
  points jsonb not null default '[]'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.dune_series enable row level security;
