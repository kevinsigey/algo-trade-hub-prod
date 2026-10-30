-- Trading HQ step 2: the Workshop's ideas and every test run on them. A verdict is saved forever, pass or fail:
-- idea_runs is insert-only, enforced here rather than trusted to the code.
create table if not exists public.ideas (
  id bigint generated always as identity primary key,
  title text not null,
  plain_words text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.idea_runs (
  id bigint generated always as identity primary key,
  idea_id bigint not null references public.ideas(id),
  variation int not null,
  spec jsonb not null,
  draft_model text,
  verdict text not null check (verdict in ('PASS', 'FAIL', 'NOT ENOUGH DATA')),
  result jsonb not null,
  data_end date,
  created_at timestamptz not null default now(),
  unique (idea_id, variation)
);

create or replace function public.idea_runs_append_only() returns trigger language plpgsql as $$
begin
  raise exception 'idea_runs is append-only: a verdict is never changed';
end
$$;

drop trigger if exists idea_runs_no_update on public.idea_runs;
create trigger idea_runs_no_update before update or delete on public.idea_runs
  for each row execute function public.idea_runs_append_only();

-- Server-side only (service role); ideas stay private until step 3 publishes them.
alter table public.ideas enable row level security;
alter table public.idea_runs enable row level security;
