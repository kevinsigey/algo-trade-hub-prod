-- Saved screens (Kevin, 2026-11-02 package, Part A2): a screen is a research
-- object -- the spec is the record, the last run (footer + survivors) rides on
-- the row, and promotion to a Workshop idea is a set-once step that points
-- back at the idea it became (the screen -> idea handoff contract: a fixed
-- basket of the run's survivors, the spec preserved as provenance).
create table if not exists public.screens (
  id bigint generated always as identity primary key,
  name text not null,
  spec jsonb not null,
  last_run jsonb,
  promoted_idea_id integer,
  promoted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.screens enable row level security;
