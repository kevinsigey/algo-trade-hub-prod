-- Chokepoints (Kevin, 2026-11-02): 15-minute physical-signal snapshots at
-- commodity chokepoints + the events they surface. Raw firehose is never
-- stored; every metric row carries its feed health (live/stale/unknown) so a
-- dead feed reads as unknown, never as zero.
create table if not exists public.geo_snapshots (
  id bigint generated always as identity primary key,
  region text not null,
  feed text not null,
  metric text not null,
  value double precision,
  detail jsonb not null default '{}'::jsonb,
  health text not null check (health in ('live', 'stale', 'unknown')),
  taken_at timestamptz not null default now()
);
create index if not exists geo_snapshots_lookup
  on public.geo_snapshots (region, metric, taken_at desc);

create table if not exists public.geo_events (
  id bigint generated always as identity primary key,
  region text not null,
  kind text not null,
  dedupe_key text not null,
  title text not null,
  detail jsonb not null default '{}'::jsonb,
  occurred_at timestamptz,
  created_at timestamptz not null default now(),
  unique (region, kind, dedupe_key)
);
create index if not exists geo_events_region_time
  on public.geo_events (region, created_at desc);

alter table public.geo_snapshots enable row level security;
alter table public.geo_events enable row level security;
