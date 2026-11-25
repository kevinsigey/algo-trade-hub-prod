-- Issue #619 (Kevin, 2026-11-25): the live lane's execution amendment
-- records its sends. attempts counts the sends on a row (1 = the first
-- send, 2 = the one bounded re-cross after an unfilled IOC); rows from
-- before the amendment carry 0, which is also the never-sent value --
-- among SENT rows, attempts = 0 therefore reads as pre-amendment.
-- filled_attempt says which send filled (1 or 2); null when nothing
-- filled. Together they are the pre/post-amendment split the 150-trade
-- edge check reads, and they distinguish first-send fills from
-- re-cross fills in the ledger.
alter table public.kalshi_live_orders add column if not exists attempts integer not null default 0;
alter table public.kalshi_live_orders add column if not exists filled_attempt integer;
