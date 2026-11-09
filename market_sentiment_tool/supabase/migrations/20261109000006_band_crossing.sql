-- Band-crossing engine (Spec C, Kevin 2026-11-09): the LOG-ONLY build's
-- storage — the mode control row, the scan audit, the per-(name, book)
-- crossing state, and the crossing log itself.
--
-- band_crossing_controls is the ONE editable switch, on the gap_controls
-- precedent (20261109000005): the engine reads the 'global' row on every
-- scan and stamps the mode on every crossing row. It is seeded FALSE and
-- this build contains no order path at all — the row is the future live
-- build's switch, and flipping it against this build activates nothing.
-- Only Kevin flips it, on his word.
--
-- band_crossings is append-only: a row is a transition (the freeze doc's
-- state machine), with the would-be action, the Portfolio Check outcome
-- recorded on the row (never a manual_actions row in log-only mode), and
-- the falsifier outcomes filled in by the nightly grading pass.
-- Service role only; no anon or authenticated access.
create table if not exists public.band_crossing_controls (
  scope text primary key,
  orders_enabled boolean not null,
  updated_at timestamptz not null default now(),
  note text
);

alter table public.band_crossing_controls enable row level security;
revoke all on public.band_crossing_controls from anon, authenticated;

insert into public.band_crossing_controls (scope, orders_enabled, note)
values ('global', false,
        'Log-only by Kevin 2026-11-09: the band-crossing engine records would-be actions and places NO orders. This row is the future live build''s switch; flipping it against the log-only build activates nothing.')
on conflict (scope) do nothing;

create table if not exists public.band_crossing_scans (
  id bigint generated always as identity primary key,
  kind text not null,
  requested_kind text,
  mode text not null,
  started_at timestamptz not null,
  finished_at timestamptz,
  sheets_watermark timestamptz,
  banded_names integer,
  state_rows integer,
  crossings_written integer,
  skipped jsonb,
  book_skips jsonb
);

alter table public.band_crossing_scans enable row level security;
revoke all on public.band_crossing_scans from anon, authenticated;

create table if not exists public.band_crossing_state (
  ticker text not null,
  book text not null,
  zone text,
  action text,
  target_pct numeric,
  guide_status text,
  t1_classification text,
  held boolean not null default false,
  sheet_computed_at timestamptz,
  updated_at timestamptz not null,
  primary key (ticker, book)
);

alter table public.band_crossing_state enable row level security;
revoke all on public.band_crossing_state from anon, authenticated;

create table if not exists public.band_crossings (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  scan_id bigint references public.band_crossing_scans (id),
  scan_kind text,
  book text not null,
  ticker text not null,
  industry text,
  band_basis text,
  bear numeric,
  base numeric,
  bull numeric,
  price numeric,
  price_as_of date,
  zone text,
  prev_action text,
  action text not null,
  target_pct numeric,
  delta_usd numeric,
  held_mv numeric,
  held_weight_pct numeric,
  guide_status text,
  guide_direction text,
  t1_classification text,
  suppress_reason text,
  pc_outcome text,
  pc_detail text,
  mode text not null,
  outcome_5 jsonb,
  outcome_20 jsonb,
  score_20 numeric
);

alter table public.band_crossings enable row level security;
revoke all on public.band_crossings from anon, authenticated;

create index if not exists band_crossings_ticker_idx
  on public.band_crossings (ticker, id desc);
