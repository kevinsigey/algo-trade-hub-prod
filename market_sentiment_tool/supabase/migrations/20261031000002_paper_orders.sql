-- Trading HQ step 4: automated PAPER orders per idea, off by default. Every switch change and every order decision
-- (sent, already sent, skipped, rejected) is insert-only, like idea_runs.
alter table public.ideas add column if not exists auto_orders boolean not null default false;

create or replace function public.ideas_auto_needs_live() returns trigger language plpgsql as $$
begin
  if new.auto_orders and (new.live_at is null or new.killed_at is not null) then
    raise exception 'automatic paper orders are only for a live idea that has not been killed';
  end if;
  return new;
end
$$;

drop trigger if exists ideas_auto_needs_live on public.ideas;
create trigger ideas_auto_needs_live before insert or update on public.ideas
  for each row execute function public.ideas_auto_needs_live();

create table if not exists public.order_switches (
  id bigint generated always as identity primary key,
  idea_id bigint not null references public.ideas(id),
  "on" boolean not null,
  by text not null,
  at timestamptz not null default now()
);

create table if not exists public.paper_orders (
  id bigint generated always as identity primary key,
  idea_id bigint not null references public.ideas(id),
  day date not null,
  symbol text not null,
  side text not null check (side in ('buy', 'sell')),
  qty integer not null check (qty >= 0),
  client_order_id text not null,
  status text not null check (status in ('sent', 'already sent', 'skipped', 'rejected')),
  reason text,
  alpaca_order_id text,
  at timestamptz not null default now()
);
create index if not exists paper_orders_idea on public.paper_orders (idea_id, id);

drop trigger if exists order_switches_no_update on public.order_switches;
create trigger order_switches_no_update before update or delete on public.order_switches
  for each row execute function public.idea_runs_append_only();

drop trigger if exists paper_orders_no_update on public.paper_orders;
create trigger paper_orders_no_update before update or delete on public.paper_orders
  for each row execute function public.idea_runs_append_only();

alter table public.order_switches enable row level security;
alter table public.paper_orders enable row level security;
