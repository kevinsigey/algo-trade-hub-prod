-- Second paper book (Kevin, 2026-11-02): live state per book. The main book's live state
-- stays on the idea row (the record since October, guarded by its set-once trigger); this
-- table carries every book's activation -- which ideas are live on the $1M book, at what
-- size, with orders on or off -- backfilled for main so the runner and the pages can read
-- one shape per book. The two books are independent on purpose: different ideas, sizes and
-- strategies per book, so one book never has to carry every live idea.
create table if not exists public.book_activations (
  book text not null,
  idea_id bigint not null references public.ideas(id),
  live_at timestamptz,
  live_run_id bigint references public.idea_runs(id),
  size_pct numeric,
  gate jsonb,
  auto_orders boolean not null default false,
  killed_at timestamptz,
  primary key (book, idea_id)
);

alter table public.paper_orders add column if not exists book text not null default 'main';
alter table public.order_switches add column if not exists book text not null default 'main';

insert into public.book_activations (book, idea_id, live_at, live_run_id, size_pct, gate, auto_orders, killed_at)
select 'main', id, live_at, live_run_id, size_pct, gate, coalesce(auto_orders, false), killed_at
from public.ideas
where live_at is not null
on conflict (book, idea_id) do nothing;
