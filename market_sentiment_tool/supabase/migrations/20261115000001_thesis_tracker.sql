-- The Thesis Tracker (Thesis v6 joining ledger; design
-- docs/superpowers/specs/2026-11-16-thesis-tracker-design.md, issue #524
-- comment 6908279417). One migration: the theses registry with
-- machine-readable falsifiers (Claims A/B/C in their fireable forms),
-- forecast cards frozen before the print, outcomes written only by the
-- grader, the trades join, the sizing-fork config + grader health, the
-- research-file staleness registry, and the regime-input registry
-- (manual entry -- two of the three credit lights have no honest free
-- feed). Applied to the VPS-local database only, on Kevin's go of
-- 2026-11-16; the cloud project stays the frozen rollback copy.
-- Every table: row security on, anon/authenticated revoked, and an
-- explicit grant to service_role -- the self-hosted stack's default
-- privileges do NOT cover the service role (the fifteen_binance repair,
-- migration 20261116000001, is the lesson).

create table if not exists public.theses (
  id bigint generated always as identity primary key,
  slug text not null unique,
  title text not null,
  sleeve text not null check (sleeve in ('core', 'systematic', 'regime', 'event_lab')),
  status text not null default 'live'
    check (status in ('live', 'shadow', 'demoted', 'killed', 'merged')),
  kill_lines jsonb not null default '[]'::jsonb,
  spec_ref text,
  created_at timestamptz not null default now()
);
alter table public.theses enable row level security;
revoke all on public.theses from anon, authenticated;
grant select, insert, update, delete on public.theses to service_role;

-- (The falsifier window column is window_spec: WINDOW is a reserved
-- word in Postgres.)
create table if not exists public.thesis_falsifiers (
  id bigint generated always as identity primary key,
  thesis_id bigint not null references public.theses (id),
  claim text not null check (claim in ('A', 'B', 'C')),
  metric text not null,
  threshold jsonb not null,
  window_spec jsonb not null,
  deadline date,
  state text not null default 'armed'
    check (state in ('armed', 'suspended', 'fired', 'passed', 'killed')),
  created_at timestamptz not null default now(),
  unique (thesis_id, claim)
);
alter table public.thesis_falsifiers enable row level security;
revoke all on public.thesis_falsifiers from anon, authenticated;
grant select, insert, update, delete on public.thesis_falsifiers to service_role;

create table if not exists public.forecast_cards (
  id bigint generated always as identity primary key,
  ticker text not null,
  thesis_id bigint not null references public.theses (id),
  print_at timestamptz not null,
  whisper_esp numeric,
  whisper_sign text check (whisper_sign in ('positive', 'negative', 'flat')),
  money_flow_direction text
    check (money_flow_direction in ('inflow', 'outflow', 'mixed')),
  money_flow_evidence jsonb not null default '[]'::jsonb,
  guide_position text,
  predicted_direction text
    check (predicted_direction in ('up', 'down', 'flat')),
  opposing_case_ref text,
  classification text
    check (classification in ('improved', 'intact', 'deteriorated')),
  supersedes_id bigint references public.forecast_cards (id),
  frozen_at timestamptz not null default now()
);
create index if not exists forecast_cards_ticker_print_idx
  on public.forecast_cards (ticker, print_at);
create index if not exists forecast_cards_print_idx
  on public.forecast_cards (print_at);
alter table public.forecast_cards enable row level security;
revoke all on public.forecast_cards from anon, authenticated;
grant select, insert, update, delete on public.forecast_cards to service_role;

-- Cards are frozen: no UPDATE ever lands. A correction is a new
-- pre-print card whose supersedes_id points at the card it replaces;
-- the latest pre-print card is the graded one.
create or replace function public.forecast_cards_freeze()
returns trigger language plpgsql as $$
begin
  raise exception 'forecast_cards are frozen: insert a superseding card instead';
end;
$$;
drop trigger if exists forecast_cards_no_update on public.forecast_cards;
create trigger forecast_cards_no_update
  before update on public.forecast_cards
  for each row execute function public.forecast_cards_freeze();

create table if not exists public.forecast_outcomes (
  id bigint generated always as identity primary key,
  card_id bigint not null unique references public.forecast_cards (id),
  graded_at timestamptz not null default now(),
  reaction_close double precision,
  ret_1d double precision,
  ret_3d double precision,
  ret_5d double precision,
  spy_1d double precision,
  spy_3d double precision,
  spy_5d double precision,
  excess_1d double precision,
  excess_3d double precision,
  excess_5d double precision,
  whisper_hit boolean,
  money_flow_hit boolean,
  classification_hit boolean
);
alter table public.forecast_outcomes enable row level security;
revoke all on public.forecast_outcomes from anon, authenticated;
grant select, insert, update, delete on public.forecast_outcomes to service_role;

create table if not exists public.trade_links (
  id bigint generated always as identity primary key,
  client_order_id text not null unique,
  book text not null,
  forecast_id bigint references public.forecast_cards (id),
  thesis_id bigint references public.theses (id),
  play_kind text check (play_kind in ('a', 'b', 'c')),
  modal_value double precision,
  opposing_case_ref text,
  shadow boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.trade_links enable row level security;
revoke all on public.trade_links from anon, authenticated;
grant select, insert, update, delete on public.trade_links to service_role;

-- The sizing fork (spec Section 4): one config row, one health row.
-- The governing unit is read from health at preflight time -- Schedule
-- v2 while the grader's last successful run is fresh, $1,500 otherwise.
create table if not exists public.tracker_config (
  id int primary key check (id = 1),
  unit_v2_premium double precision not null default 5000,
  unit_v2_top double precision not null default 10000,
  unit_fallback double precision not null default 1500,
  play_kind_c_live boolean not null default false,
  cash_floor_pct double precision not null default 10
);
alter table public.tracker_config enable row level security;
revoke all on public.tracker_config from anon, authenticated;
grant select, insert, update, delete on public.tracker_config to service_role;

create table if not exists public.tracker_health (
  id int primary key check (id = 1),
  last_grader_run_at timestamptz,
  last_grader_ok boolean not null default false
);
alter table public.tracker_health enable row level security;
revoke all on public.tracker_health from anon, authenticated;
grant select, insert, update, delete on public.tracker_health to service_role;

create table if not exists public.research_files (
  id bigint generated always as identity primary key,
  path text not null unique,
  thesis_id bigint references public.theses (id),
  amended_at timestamptz,
  last_decision_at timestamptz
);
alter table public.research_files enable row level security;
revoke all on public.research_files from anon, authenticated;
grant select, insert, update, delete on public.research_files to service_role;

create table if not exists public.regime_inputs (
  id bigint generated always as identity primary key,
  key text not null unique,
  state text not null default 'unknown',
  detail jsonb not null default '{}'::jsonb,
  as_of timestamptz,
  source_note text
);
alter table public.regime_inputs enable row level security;
revoke all on public.regime_inputs from anon, authenticated;
grant select, insert, update, delete on public.regime_inputs to service_role;

-- Seeds: the v6 structure (spec Section 6 dispositions).
insert into public.theses (slug, title, sleeve, status, spec_ref) values
  ('event-lab', 'Event lab (T1 rebuilt)', 'event_lab', 'live',
   'thesis_v6_spec_2026-11-15.md#event-lab'),
  ('core', 'Core beta (T3+T8 merged)', 'core', 'live',
   'thesis_v6_spec_2026-11-15.md#core'),
  ('systematic', 'Systematic (T4, W18 as tested)', 'systematic', 'live',
   'thesis_v6_spec_2026-11-15.md#systematic'),
  ('regime', 'Regime (Gray Area minimax sleeves)', 'regime', 'live',
   'thesis_v6_spec_2026-11-15.md#regime')
on conflict (slug) do nothing;

insert into public.thesis_falsifiers
  (thesis_id, claim, metric, threshold, window_spec, deadline, state)
select t.id, 'A', 'classification_separation',
  '{"min_separation": 0.60, "demote_below": 0.60, "kill_below_rolling": 0.50}'::jsonb,
  '{"prints": 40, "rolling_kill_prints": 60, "counting": "pre-print timestamps only; no-trades are controls"}'::jsonb,
  date '2027-03-01', 'armed'
from public.theses t where t.slug = 'event-lab'
on conflict (thesis_id, claim) do nothing;

insert into public.thesis_falsifiers
  (thesis_id, claim, metric, threshold, window_spec, deadline, state)
select t.id, 'B', 'supplier_excess_per_cluster',
  '{"kill_mean_excess_max": 0.0, "min_positive_clusters": 3, "suspend_on_capex_cuts_in_round": 2}'::jsonb,
  '{"clusters": 4, "era": "2027 hyperscaler print clusters"}'::jsonb,
  date '2027-11-30', 'armed'
from public.theses t where t.slug = 'event-lab'
on conflict (thesis_id, claim) do nothing;

insert into public.thesis_falsifiers
  (thesis_id, claim, metric, threshold, window_spec, deadline, state)
select t.id, 'C', 'play_kind_a_net_after_costs',
  '{"must_net_positive": true}'::jsonb,
  '{"fires": 5}'::jsonb,
  date '2027-03-01', 'armed'
from public.theses t where t.slug = 'event-lab'
on conflict (thesis_id, claim) do nothing;

insert into public.tracker_config (id) values (1) on conflict (id) do nothing;
insert into public.tracker_health (id) values (1) on conflict (id) do nothing;

-- Regime registry seeds (manual entry; states as of the 2026-11-16
-- regime note, maintained by the trading chat from here).
insert into public.regime_inputs (key, state, detail, as_of, source_note) values
  ('big4_capex_2027', 'unknown',
   '{"crash_below_usd_bn": 620, "boom_at_or_above_usd_bn": 950}'::jsonb,
   null, 'Running figure maintained by the trading chat; Gray Area grading lines from Thesis v6'),
  ('credit_light_dc_yields', 'unknown', '{}'::jsonb, null,
   'Data-center borrowing yields; no honest free feed -- state set by hand'),
  ('credit_light_redemption_gates', 'flickering', '{}'::jsonb,
   '2026-11-16T00:00:00Z', 'Private-credit redemption gates flickering per Bank of England (regime note, 2026-11-16)'),
  ('credit_light_bank_lending', 'off', '{}'::jsonb,
   '2026-11-16T00:00:00Z', 'Bank lending tightening still off (regime note, 2026-11-16); this light turning on is a crash-grade input on its own'),
  ('crash_triggers', 'unknown', '{"fired": []}'::jsonb, null,
   'Gray Area crash-trigger states, maintained by the trading chat')
on conflict (key) do nothing;
