-- A rebalance hands a book's manual shares of a symbol to an idea (Kevin, 2026-11-04: move the correct number of
-- shares, don't close and reopen). The morning order job reads this and writes the matching order_labels; a move
-- covers shares held when it was made, never later manual orders.
create table if not exists public.manual_moves (
  id bigint generated always as identity primary key,
  book text not null,
  symbol text not null,
  idea_id bigint not null references public.ideas(id),
  by text not null,
  at timestamptz not null default now()
);

drop trigger if exists manual_moves_no_update on public.manual_moves;
create trigger manual_moves_no_update before update or delete on public.manual_moves
  for each row execute function public.idea_runs_append_only();

-- Server-side only (service role).
alter table public.manual_moves enable row level security;
revoke all on public.manual_moves from anon, authenticated;
