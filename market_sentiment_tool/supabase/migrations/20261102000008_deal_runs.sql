-- Deal runs (Kevin, 2026-11-02 package, Part B): a builder run is a saved
-- research draft -- inputs + computed outputs are the record, and the AI
-- summary (a labelled draft) is written back onto the same row.
create table if not exists public.deal_runs (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('ipo', 'ma')),
  name text not null,
  inputs jsonb not null,
  outputs jsonb not null,
  summary text,
  summary_model text,
  created_at timestamptz not null default now()
);

alter table public.deal_runs enable row level security;
