-- QQQ benchmark for the Portfolio page (Kevin's go, 2026-11-12): snapshots
-- carry the QQQ price beside spy_price so the header today split, the
-- scoreboard, and the Performance curve can show the Nasdaq-100 ETF next to
-- SPY. Written by tradehub/portfolio/service.py::take_snapshot going
-- forward; existing rows are backfilled by
-- tradehub/scripts/portfolio_qqq_backfill.py from QQQ hourly bars (close of
-- the last fully-closed hourly bar at each snapshot's taken_at).
alter table public.portfolio_snapshots
  add column if not exists qqq_price double precision;
