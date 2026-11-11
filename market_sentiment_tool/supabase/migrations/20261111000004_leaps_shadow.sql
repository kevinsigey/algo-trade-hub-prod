-- Spec F LEAPS shadow trial (Workshop idea 81, family T8-LEAPS-1,
-- preregistered 2026-11-11, shadow-first per Kevin's 2026-11-11 14:50 CT
-- amendment): one row per trigger the trial consumes. An opened pair
-- carries both shadow lines -- the deep-ITM LEAPS line priced off the live
-- chain at capture and the share line at identical delta-notional -- plus
-- the latest nightly marks. A trigger that cannot open a line (no contract
-- in the delta band, extrinsic over the cap, one contract over the premium
-- cap, no quote) is recorded with status 'unfilled' and its reason in
-- close_reason; it does not count toward the trial's 4. Repeat crossings
-- on a name with an open pair ride in that pair's events list. Written by
-- tradehub/scripts/leaps_shadow_grade.py (via tradehub/leaps_shadow.py);
-- read by the Workshop idea page (idea tagged 'leaps-trial').
create table if not exists public.leaps_shadow_pairs (
  id bigint generated always as identity primary key,
  idea_id int not null,
  crossing_id bigint,
  ticker text not null,
  opened_at timestamptz not null,
  status text not null,
  close_reason text,
  closed_at timestamptz,
  snapshot_id bigint,
  zone text,
  action text,
  bear real,
  base real,
  bull real,
  guide_status text,
  trigger_price real,
  occ_symbol text,
  strike real,
  expiry date,
  contracts int,
  entry_bid real,
  entry_mid real,
  entry_ask real,
  premium_total real,
  delta_at_entry real,
  extrinsic_at_entry real,
  iv_at_entry real,
  spot_at_entry real,
  delta_notional real,
  share_shares real,
  share_entry_price real,
  marked_at timestamptz,
  leaps_mid real,
  mark_stale boolean not null default false,
  share_price real,
  dte int,
  roll_flag boolean not null default false,
  leaps_pnl real,
  share_pnl real,
  delta_delivered real,
  carry_drag_pct real,
  events jsonb not null default '[]'::jsonb
);
create unique index if not exists leaps_shadow_pairs_crossing_idx
  on public.leaps_shadow_pairs (crossing_id) where crossing_id is not null;
create index if not exists leaps_shadow_pairs_idea_status_idx
  on public.leaps_shadow_pairs (idea_id, status);
alter table public.leaps_shadow_pairs enable row level security;
revoke all on public.leaps_shadow_pairs from anon, authenticated;
