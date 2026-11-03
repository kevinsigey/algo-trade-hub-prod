-- Health counted frozen forecasts by reading rows, which PostgREST caps at 1000, while the journal now freezes
-- about 19k a day: most families read as "froze nothing". Count in the database instead.
CREATE OR REPLACE FUNCTION public.journal_frozen_counts(since timestamptz)
RETURNS TABLE (forecaster text, day date, n bigint)
LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT forecaster, (frozen_at AT TIME ZONE 'America/Chicago')::date AS day, count(*) AS n
  FROM public.journal_forecasts WHERE frozen_at >= since GROUP BY 1, 2
$$;
REVOKE ALL ON FUNCTION public.journal_frozen_counts(timestamptz) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.journal_frozen_counts(timestamptz) TO service_role;
