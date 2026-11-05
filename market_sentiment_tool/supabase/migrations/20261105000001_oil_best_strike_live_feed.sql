-- The Oil page prices off the live Hyperliquid perp, so the record beside its pick now replays the rows frozen on
-- that same feed (wti-hourly-v4-hl-shadow, since 2026-11-04). The old replay graded the delayed CL=F model, which
-- the page no longer shows. Same rule, same fee; only the rows change.
CREATE OR REPLACE FUNCTION public.oil_best_strike_backtest()
RETURNS TABLE (events bigint, picks bigint, hits bigint, avg_model double precision, avg_cost double precision,
               net_per_contract double precision)
LANGUAGE sql STABLE SET search_path = public AS $$
  WITH f AS (
    SELECT left(f.target, position('-T' in f.target) - 1) AS ev, f.probability AS p,
           (f.payload->>'yes_bid')::float AS bid, (f.payload->>'yes_ask')::float AS ask, s.outcome AS o
    FROM public.journal_forecasts f JOIN public.journal_settlements s ON s.target = f.target
    WHERE f.forecaster = 'oil_wti_hourly' AND f.forecaster_version = 'wti-hourly-v4-hl-shadow'
      AND f.payload->>'yes_bid' IS NOT NULL AND f.payload->>'yes_ask' IS NOT NULL
      AND (f.payload->>'yes_ask')::float - (f.payload->>'yes_bid')::float <= 0.08
  ), sides AS (
    SELECT ev, p AS sp, ask AS c, o AS w FROM f WHERE ask BETWEEN 0.20 AND 0.80
    UNION ALL SELECT ev, 1 - p, 1 - bid, 1 - o FROM f WHERE 1 - bid BETWEEN 0.20 AND 0.80
  ), best AS (
    SELECT DISTINCT ON (ev) ev, sp, c, w FROM sides WHERE sp - c >= 0.05
    ORDER BY ev, sp - c - 0.07 * c * (1 - c) DESC
  )
  SELECT (SELECT count(DISTINCT ev) FROM f), count(*), coalesce(sum(w), 0)::bigint, avg(sp), avg(c),
         avg(w - c - 0.07 * c * (1 - c))
  FROM best
$$;
REVOKE ALL ON FUNCTION public.oil_best_strike_backtest() FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.oil_best_strike_backtest() TO service_role;
