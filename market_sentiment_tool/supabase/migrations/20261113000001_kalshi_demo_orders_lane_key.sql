-- Kalshi demo candidate lane (action plan Step B.3): a second lane trades
-- the preregistered v4-edge20-shadow candidate beside the live gate on the
-- same demo account, so one decision can hold one order row per lane. The
-- never-order-twice key widens from (series, target) to
-- (series, target, gate_version), and gate_version becomes required so
-- every row names its lane. Applied 2026-11-13 by Claude through the
-- Supabase connector (version 20261113021744) on Kevin's go, before this
-- file shipped; read back: 1 live row, 0 null gate_versions.
alter table public.kalshi_demo_orders
  alter column gate_version set not null;
alter table public.kalshi_demo_orders
  drop constraint kalshi_demo_orders_series_target_key;
alter table public.kalshi_demo_orders
  add constraint kalshi_demo_orders_series_target_gate_key
  unique (series, target, gate_version);
