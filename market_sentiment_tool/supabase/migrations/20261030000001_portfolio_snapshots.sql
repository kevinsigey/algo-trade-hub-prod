-- Trading HQ step 1: the paper account's value over time, so the public equity curve has history of
-- its own. One row per snapshot; "since start" is the first row for the account in PORTFOLIO_ACCOUNT_NUMBER.
create table if not exists public.portfolio_snapshots (
  taken_at timestamptz not null default now(),
  account_number text not null,
  equity double precision not null,
  cash double precision not null,
  spy_price double precision not null,
  primary key (account_number, taken_at)
);

-- Server-side reads and writes only (service role); no anon policy.
alter table public.portfolio_snapshots enable row level security;
