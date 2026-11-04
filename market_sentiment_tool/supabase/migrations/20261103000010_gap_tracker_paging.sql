-- Gap tracker reads that hold up past the API's row cap. Pairs page by ticker, so the evidence count
-- can't silently stop at one response. Unresolved contracts come newest first within 14 days, so void
-- or scalar markets, which never get an outcome, can't fill the batch and starve newer ones.
DROP FUNCTION IF EXISTS public.gap_first_pairs();
CREATE OR REPLACE FUNCTION public.gap_first_pairs(after_ticker text, max_rows integer)
RETURNS TABLE (ticker text, category text, model double precision, market double precision, outcome smallint)
LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT s.ticker, s.category, s.model_prob, s.mid, o.outcome
  FROM (SELECT DISTINCT ON (ticker) ticker, category, model_prob, mid FROM public.gap_snapshots
        WHERE model_prob IS NOT NULL AND mid IS NOT NULL AND ticker > after_ticker ORDER BY ticker, taken_at) s
  JOIN public.gap_outcomes o USING (ticker)
  ORDER BY s.ticker
  LIMIT max_rows
$$;
REVOKE ALL ON FUNCTION public.gap_first_pairs(text, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.gap_first_pairs(text, integer) TO service_role;

CREATE OR REPLACE FUNCTION public.gap_unresolved(asof timestamptz, max_rows integer)
RETURNS TABLE (ticker text)
LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT s.ticker FROM public.gap_snapshots s
  LEFT JOIN public.gap_outcomes o USING (ticker)
  WHERE o.ticker IS NULL AND s.settles_at < asof AND s.settles_at > asof - interval '14 days'
  GROUP BY s.ticker
  ORDER BY max(s.settles_at) DESC
  LIMIT max_rows
$$;
