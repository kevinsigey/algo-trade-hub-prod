-- Contracts on offer at the best ask on each side, recorded with every minute tick (Kevin, 2026-11-10).
-- The 15-minute rule's paper record assumes a fill at the quoted ask; these say how many contracts that
-- ask could have filled. Null on rows written before this column existed or when the book read failed.
alter table public.fifteen_min_ticks add column if not exists yes_ask_size real;
alter table public.fifteen_min_ticks add column if not exists no_ask_size real;
