-- Level Watcher / Trigger Service (Spec D, Stage 1 — Rung 1 alerts,
-- Kevin 2026-11-09): the watch store, the trigger log (the scorecard),
-- the alert outbox, heartbeats, the governor framework, grading state,
-- and the volume-baseline day cache.
--
-- Stage 1 is alert-only BY CONSTRUCTION: there is no order table here
-- and no order code reads these tables. A watch carries its requested
-- rung; every fire is stamped rung_effective = 1.
--
-- watcher_fires.idempotency_key is UNIQUE — the database-level
-- backstop behind the one-fire-per-watch-per-day rule, so a watcher
-- restart that re-touches a level cannot double-fire.
--
-- Governor numbers (daily_profit_target_usd / daily_loss_stop_usd)
-- are NULL until Kevin sets them: the spec's placeholder defaults
-- (2x/3x the standard unit) are deliberately NOT seeded anywhere.
--
-- band_crossings gains snapshot_id (additive, nullable): the
-- provenance field for the Guidance Reliability lane's persisted band
-- snapshots. Watcher-written crossing rows stamp it from the sheet
-- (null until that lane's compute stamps sheets); scan-written rows
-- leave it null. One provenance scheme, shared by both lanes.
-- Service role only; no anon or authenticated access.
create table if not exists public.level_watches (
  id bigint generated always as identity primary key,
  name text not null,
  family text not null,
  kind text not null default 'level',
  instrument text not null,
  trigger_type text,
  level numeric,
  level_hi numeric,
  hold_minutes integer,
  conditions jsonb not null default '{}'::jsonb,
  intent text not null default 'none',
  rung integer not null default 1,
  book text,
  action jsonb,
  governor_group text,
  allow_multi_fire boolean not null default false,
  enabled boolean not null default true,
  expires_at timestamptz,
  disabled_reason text,
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.level_watches enable row level security;
revoke all on public.level_watches from anon, authenticated;

create table if not exists public.watcher_fires (
  id bigint generated always as identity primary key,
  watch_id bigint references public.level_watches (id),
  family text,
  instrument text not null,
  session_date date not null,
  fired_at timestamptz not null,
  rung_effective integer not null default 1,
  trigger_price numeric,
  level numeric,
  detail jsonb,
  price_path_past jsonb,
  price_path_future jsonb,
  crossing_ids jsonb,
  intent text,
  idempotency_key text not null,
  ret_1 numeric,
  ret_5 numeric,
  score_1 numeric,
  score_5 numeric,
  graded_at timestamptz,
  created_at timestamptz not null default now()
);

alter table public.watcher_fires enable row level security;
revoke all on public.watcher_fires from anon, authenticated;

create unique index if not exists watcher_fires_idempotency_idx
  on public.watcher_fires (idempotency_key);

create index if not exists watcher_fires_family_idx
  on public.watcher_fires (family, id desc);

create table if not exists public.watcher_alerts (
  id bigint generated always as identity primary key,
  kind text not null,
  watch_id bigint references public.level_watches (id),
  family text,
  title text not null,
  body text not null,
  evidence jsonb,
  status text not null default 'pending',
  delivered_at timestamptz,
  delivery_note text,
  created_at timestamptz not null default now()
);

alter table public.watcher_alerts enable row level security;
revoke all on public.watcher_alerts from anon, authenticated;

create index if not exists watcher_alerts_pending_idx
  on public.watcher_alerts (status, id desc);

create table if not exists public.watcher_heartbeats (
  id bigint generated always as identity primary key,
  at timestamptz not null,
  session_date date not null,
  note text
);

alter table public.watcher_heartbeats enable row level security;
revoke all on public.watcher_heartbeats from anon, authenticated;

create table if not exists public.watcher_governor_groups (
  name text primary key,
  standard_unit_usd numeric,
  daily_profit_target_usd numeric,
  daily_loss_stop_usd numeric,
  note text,
  updated_at timestamptz not null default now()
);

alter table public.watcher_governor_groups enable row level security;
revoke all on public.watcher_governor_groups from anon, authenticated;

create table if not exists public.watcher_governor_state (
  group_name text not null,
  session_date date not null,
  disarmed boolean not null default false,
  reason text,
  day_pnl_usd numeric,
  updated_at timestamptz not null default now(),
  primary key (group_name, session_date)
);

alter table public.watcher_governor_state enable row level security;
revoke all on public.watcher_governor_state from anon, authenticated;

create table if not exists public.watcher_family_state (
  family text primary key,
  graded_count integer not null default 0,
  mean_score_5 numeric,
  demoted_at timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.watcher_family_state enable row level security;
revoke all on public.watcher_family_state from anon, authenticated;

create table if not exists public.watcher_day_cache (
  symbol text not null,
  session_date date not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  primary key (symbol, session_date)
);

alter table public.watcher_day_cache enable row level security;
revoke all on public.watcher_day_cache from anon, authenticated;

alter table public.band_crossings
  add column if not exists snapshot_id bigint;
