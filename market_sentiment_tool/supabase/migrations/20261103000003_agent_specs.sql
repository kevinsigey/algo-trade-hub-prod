-- In-site agent, phases 1-2 (Kevin, 2026-11-03): the specs the interpreter
-- produces and Kevin confirms, with their lifecycle state (draft -> shadow ->
-- paper-eligible, or blocked) and the accuracy gate's last outcome. Phase 3's
-- compiler will read paper-eligible specs from here; nothing in this table
-- places an order by itself.
create table if not exists public.agent_specs (
  id bigint generated always as identity primary key,
  title text not null,
  spec jsonb not null,
  questions jsonb not null default '[]'::jsonb,
  state text not null default 'draft'
    check (state in ('draft', 'shadow', 'paper-eligible', 'blocked')),
  gate jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.agent_specs enable row level security;
