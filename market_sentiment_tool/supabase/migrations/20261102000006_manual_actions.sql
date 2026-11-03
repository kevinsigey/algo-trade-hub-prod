-- Manual actions (Kevin, 2026-11-02): when the auto-trader reaches something it must
-- not do alone -- an option with no tradable quote, an expiring short, a spread whose
-- one contract risks more than the idea's budget -- it records the action here instead
-- of guessing. The Portfolio page's "Needs your hand" box reads this table; resolving
-- an action is Kevin's click, never the runner's. `book` from day one: actions belong
-- to the book whose runner raised them.
create table if not exists public.manual_actions (
  id bigint generated always as identity primary key,
  book text not null default 'main',
  idea_id integer,
  kind text not null,
  symbol text,
  detail text not null,
  state text not null default 'open' check (state in ('open', 'done', 'dismissed')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create index if not exists manual_actions_open_idx
  on public.manual_actions (book, state, created_at desc);

alter table public.manual_actions enable row level security;
