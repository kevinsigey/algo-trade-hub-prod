-- Grants repair for the Binance-tape gold shadow (migration
-- 20261114000001): the two tables were created with row security on and
-- anon/authenticated revoked, but no grant to service_role. On the cloud
-- project, Supabase's default privileges covered the service role; on
-- the self-hosted stack they do not, so the runner's PostgREST reads and
-- writes fail with 42501 (permission denied) -- first seen 2026-11-16 in
-- fifteen_min_run's fifteen_binance_eval pass. Grant the service role
-- full access; anon/authenticated stay revoked, per the original
-- migration's intent (the shadow is read from the tables until a surface
-- is commissioned).
grant select, insert, update, delete
  on public.fifteen_binance_decisions to service_role;
grant select, insert, update, delete
  on public.fifteen_binance_evals to service_role;
