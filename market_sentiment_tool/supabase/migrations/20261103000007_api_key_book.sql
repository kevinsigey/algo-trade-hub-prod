-- Per-book machine keys (Kevin, 2026-11-03): a machine key is bound to ONE
-- paper book, so Muse can hold a key for the $1M book without it ever
-- being able to see or touch the main book (and the existing main-book key
-- can never reach the big book). The machine routes read the book from the
-- key row; existing keys backfill to 'main', the only book that existed
-- when they were minted. RLS on api_keys is already enabled
-- (20261103000004_rls_machine_and_book_tables.sql); a new column needs no
-- new policy.
alter table public.api_keys
  add column if not exists book text not null default 'main';

comment on column public.api_keys.book is
  'The paper book this key is bound to (tradehub.portfolio.books names). The /api/v1 routes place, read and cancel only on this book.';
