-- Trading HQ step 3: the Ideas record and the live-paper gate. An idea is published, goes live and is killed at
-- most once each; its daily shadow record and every trade relabel are insert-only, like idea_runs.
alter table public.ideas
  add column if not exists published_at timestamptz,
  add column if not exists live_at timestamptz,
  add column if not exists killed_at timestamptz,
  add column if not exists size_pct numeric check (size_pct > 0 and size_pct <= 100),
  add column if not exists live_run_id bigint references public.idea_runs(id),
  add column if not exists gate jsonb;

create or replace function public.ideas_lifecycle_once() returns trigger language plpgsql as $$
begin
  if (old.published_at is not null and new.published_at is distinct from old.published_at)
     or (old.live_at is not null and (new.live_at is distinct from old.live_at
         or new.size_pct is distinct from old.size_pct or new.live_run_id is distinct from old.live_run_id
         or new.gate is distinct from old.gate))
     or (old.killed_at is not null and new.killed_at is distinct from old.killed_at) then
    raise exception 'an idea is published, goes live and is killed once; that record is never changed';
  end if;
  if new.killed_at is not null and new.live_at is null then
    raise exception 'only a live idea can be killed';
  end if;
  return new;
end
$$;

drop trigger if exists ideas_lifecycle_once on public.ideas;
create trigger ideas_lifecycle_once before update on public.ideas
  for each row execute function public.ideas_lifecycle_once();

create table if not exists public.idea_shadow_days (
  id bigint generated always as identity primary key,
  idea_id bigint not null references public.ideas(id),
  day date not null,
  ret double precision not null,
  "on" boolean not null,
  bench double precision not null,
  spy double precision not null,
  created_at timestamptz not null default now(),
  unique (idea_id, day)
);

create table if not exists public.order_labels (
  id bigint generated always as identity primary key,
  order_id text not null,
  idea_id bigint references public.ideas(id),
  by text not null,
  at timestamptz not null default now()
);
create index if not exists order_labels_order_id on public.order_labels (order_id);

drop trigger if exists idea_shadow_days_no_update on public.idea_shadow_days;
create trigger idea_shadow_days_no_update before update or delete on public.idea_shadow_days
  for each row execute function public.idea_runs_append_only();

drop trigger if exists order_labels_no_update on public.order_labels;
create trigger order_labels_no_update before update or delete on public.order_labels
  for each row execute function public.idea_runs_append_only();

-- Server-side only (service role). The public Ideas record is served by the API, which shows published ideas only.
alter table public.idea_shadow_days enable row level security;
alter table public.order_labels enable row level security;
