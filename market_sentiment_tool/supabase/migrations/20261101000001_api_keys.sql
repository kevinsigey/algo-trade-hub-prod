-- Trading system phase 2, machine API step 1 (spec 2026-11-01 §1.2/§1.5): the key and audit
-- tables. No /api/v1 routes exist yet -- this step is safe with the feature entirely dark.
-- The key itself is NEVER stored: only its SHA-256 hash, so a database read cannot be turned
-- into a working key. Revocation is a timestamp, checked on every request; rotation is
-- revoke + create. Events are the audit trail for every machine-API call (and for the key
-- lifecycle itself); detail stays short and never carries payloads or key material.

create table if not exists public.api_keys (
  id bigint generated always as identity primary key,
  label text not null,
  key_hash text not null unique,
  scopes text[] not null default '{}',
  max_qty integer not null default 100 check (max_qty > 0),
  max_notional numeric not null default 25000 check (max_notional > 0),
  daily_cap integer not null default 50 check (daily_cap > 0),
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);

create table if not exists public.api_key_events (
  id bigint generated always as identity primary key,
  key_id bigint not null references public.api_keys(id),
  at timestamptz not null default now(),
  route text not null,
  client_order_id text,
  outcome text not null,
  detail text
);

create index if not exists api_key_events_key_at on public.api_key_events (key_id, at desc);
