-- Guidance snapshot integrity (Kevin, 2026-11-09 reliability pass F1-F4):
-- the Guidance page served an unversioned latest-per-ticker mix from the
-- append-only fact-sheet table while the EDGAR fleet was ingesting and
-- recompute passes were appending -- successive loads under one "as of"
-- date showed different datasets with no version label (scar tissue #9:
-- unstamped snapshot divergence).
--
-- valuation_snapshots: one row per FULL fact-sheet compute. A compute
-- opens a snapshot, stamps every sheet it writes with the snapshot id,
-- and completes the snapshot when the last sheet lands. Readers serve
-- ONLY the latest completed snapshot -- a recompute in flight never
-- changes what the page/API serve; it publishes a new snapshot whole.
--
-- valuation_band_history: per name per snapshot, a COMPACT reference
-- record (Kevin's design directive, 2026-11-09 22:03 CT): only what a
-- crossing grade or a page reconstruction needs -- guide low/high + unit,
-- direction, multiple, bands, price, zone. No fact-sheet payloads, no
-- peer detail (group/count live once per name as current state on the
-- sheets), no fundamentals; the gap recomputes from the stored fields.
-- Basis is per-snapshot state (names switch EPS <-> revenue as records
-- land). Latest filing wins is the system's semantics: a name updates
-- when a newer filing lands, and the snapshot stamp is what makes that
-- update visible instead of silent.
--
-- fact_sheets gain the snapshot id + the persisted reason columns;
-- band_crossings gains the trigger source stamp (its snapshot_id column
-- already exists); band_crossing_scans records which snapshot a scan
-- read; guidance_records gains the ingest sanity flag (BKNG's $0.00B
-- class: flag + surface, never silently rewrite the record).
-- Service role only; no anon or authenticated access.

create table if not exists public.valuation_snapshots (
  id bigint generated always as identity primary key,
  computed_at timestamptz not null,
  completed_at timestamptz,
  source text not null default 'valuation_run',
  sheet_count integer,
  banded_count integer,
  created_at timestamptz not null default now()
);

alter table public.valuation_snapshots enable row level security;
revoke all on public.valuation_snapshots from anon, authenticated;

create table if not exists public.valuation_band_history (
  id bigint generated always as identity primary key,
  snapshot_id bigint not null references public.valuation_snapshots(id),
  ticker text not null,
  band_basis text,
  guide_metric text,
  guide_unit text,
  guide_low numeric,
  guide_high numeric,
  direction text,
  peer_multiple numeric,
  bear numeric,
  base numeric,
  bull numeric,
  price numeric,
  zone text,
  computed_at timestamptz not null,
  unique (snapshot_id, ticker)
);

alter table public.valuation_band_history enable row level security;
revoke all on public.valuation_band_history from anon, authenticated;

alter table public.valuation_fact_sheets
  add column if not exists snapshot_id bigint,
  add column if not exists guard_rejections jsonb,
  add column if not exists stale_reasons jsonb,
  add column if not exists ingest_notes jsonb,
  add column if not exists price_vendor text;

alter table public.band_crossings
  add column if not exists source text not null default 'scan';

alter table public.band_crossing_scans
  add column if not exists snapshot_id bigint;

alter table public.guidance_records
  add column if not exists ingest_flag text;
