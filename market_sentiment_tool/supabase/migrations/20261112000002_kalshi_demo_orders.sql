-- Kalshi DEMO auto-trader for the 15-minute natural gas rule (Kevin approved
-- the runner 2026-11-11; sizing amended by Kevin 2026-11-12: 1% of the demo
-- balance per traded decision, scaling with balance, instead of a fixed
-- 1 contract). Written ONLY by tradehub/scripts/kalshi_demo_run.py (via
-- tradehub/kalshi_demo.py) against the Kalshi DEMO host; read by
-- /api/kalshi-demo. One row per traded (or skipped) decision: the unique
-- (series, target) is the never-order-twice guarantee.
create table if not exists public.kalshi_demo_orders (
  id bigint generated always as identity primary key,
  series text not null,               -- Kalshi series, 'KXNATGAS15M'
  target text not null,               -- fifteen_rule_decisions.target, verbatim ('kalshi:...')
  ticker text not null,               -- Kalshi market ticker (order body)
  side text not null,                 -- 'yes' | 'no' (from the decision)
  gate_version text,                  -- decision's gate stamp at trade time
  contracts int not null,             -- sized contracts (1% rule); 0 on skip rows
  contracts_filled int not null default 0,
  limit_price real not null,          -- frozen quote = decision.cost, dollars
  frozen_quote real not null,         -- same value under its report name: slippage = fill - frozen
  ask_size int,                       -- contracts on offer at the side's ask (fifteen_min_ticks, nearest the runner pass); NULL when no tape row
  balance_at_sizing real,             -- demo balance the 1% sizing read, dollars
  budget_pct real,                    -- the pct applied (0.01 at launch)
  kalshi_order_id text,               -- NULL until placed / on skip rows
  client_order_id text,               -- deterministic per (series, target)
  status text not null,               -- pending|resting|filled|cancelled|settled|skipped_cap|skipped_no_depth
  skip_reason text,                   -- daily_contract_cap|daily_loss_cap|placement_interrupted (skip/cancel rows)
  fill_price real,                    -- average fill price, dollars
  filled_at timestamptz,
  window_close timestamptz,           -- decision close_time; cutoff logic + tab countdown
  expires_at timestamptz,             -- order expiration_ts sent to Kalshi
  outcome int,                        -- settlement: 1 yes won / 0 no won, once known
  settlement_pnl real,                -- realised demo P&L for the row, dollars, fee-netted
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (series, target)
);
create index if not exists kalshi_demo_orders_created_idx
  on public.kalshi_demo_orders (created_at);
alter table public.kalshi_demo_orders enable row level security;
revoke all on public.kalshi_demo_orders from anon, authenticated;
