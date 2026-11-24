-- The live micro-pilot's record (Kevin's ruling, 2026-11-23; issue
-- #590; preregistration docs/superpowers/specs/2026-11-23-kalshi-live-
-- pilot-prereg.md): the 15-minute oil & gas RAW rule trades Kevin's
-- LIVE Kalshi account at one contract per decision from a ~$10 start.
-- One row per (series, target, lane) under a unique constraint -- the
-- never-order-twice guarantee -- carrying the decision's frozen quote,
-- the live ask at send, the fill and its slippage against the frozen
-- paper price, the fee actually charged, the decision-to-send latency,
-- the settled outcome and P&L, and the paper twin's P&L on the same
-- window. Written and read by tradehub/kalshi_live_lane.py; the only
-- writer of live orders is that lane, behind the live client's
-- three-condition guard.
create table if not exists public.kalshi_live_orders (
  id bigint generated always as identity primary key,
  series text not null,
  target text not null,
  lane text not null,
  ticker text not null,
  side text not null,
  decision_id bigint,
  model_prob double precision,
  frozen_quote double precision not null,
  frozen_at timestamptz,
  window_close timestamptz,
  live_ask double precision,
  slippage double precision,
  contracts_requested integer not null default 0,
  contracts_filled integer not null default 0,
  fill_price double precision,
  fee_usd double precision,
  kalshi_order_id text,
  client_order_id text,
  sent_at timestamptz,
  latency_s double precision,
  balance_at_sizing double precision,
  status text not null,
  skip_reason text,
  last_error text,
  outcome integer,
  pnl double precision,
  paper_pnl double precision,
  created_at timestamptz not null default now(),
  settled_at timestamptz,
  unique (series, target, lane)
);

create index if not exists kalshi_live_orders_created_idx
  on public.kalshi_live_orders (created_at);

alter table public.kalshi_live_orders enable row level security;
revoke all on public.kalshi_live_orders from anon, authenticated;
grant select, insert, update, delete on public.kalshi_live_orders to service_role;

-- The lane's persistent state: the halt (never lifted automatically),
-- the two gates' results, and the stage-3 unlock. One row per key.
create table if not exists public.kalshi_live_state (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.kalshi_live_state enable row level security;
revoke all on public.kalshi_live_state from anon, authenticated;
grant select, insert, update, delete on public.kalshi_live_state to service_role;
