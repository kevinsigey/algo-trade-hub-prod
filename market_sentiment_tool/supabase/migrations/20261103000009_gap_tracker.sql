-- The Kalshi gap tracker: a research log and paper ledger beside the frozen journal, never in it.
-- No order path reads these tables. Backend only: RLS on, no grants to anon or authenticated.
CREATE TABLE IF NOT EXISTS public.gap_snapshots (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  taken_at timestamptz NOT NULL,
  category text NOT NULL,
  series text NOT NULL,
  event_ticker text,
  ticker text NOT NULL,
  settles_at timestamptz NOT NULL,
  resolution_source text,
  rule_summary text,
  model text NOT NULL,
  model_prob double precision,
  model_data_age_s double precision,
  yes_bid double precision,
  yes_ask double precision,
  no_bid double precision,
  no_ask double precision,
  mid double precision,
  last_price double precision,
  spread double precision,
  volume double precision,
  open_interest double precision,
  side text,
  gap_pts double precision,
  exit_slippage double precision,
  failed text[] NOT NULL DEFAULT '{}',
  flagged boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS gap_snapshots_taken_idx ON public.gap_snapshots (taken_at DESC);
CREATE INDEX IF NOT EXISTS gap_snapshots_ticker_idx ON public.gap_snapshots (ticker, taken_at);

CREATE TABLE IF NOT EXISTS public.gap_outcomes (
  ticker text PRIMARY KEY,
  outcome smallint NOT NULL CHECK (outcome IN (0, 1)),
  resolved_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.gap_positions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ticker text NOT NULL UNIQUE,
  category text NOT NULL,
  settles_at timestamptz NOT NULL,
  side text NOT NULL,
  opened_at timestamptz NOT NULL,
  model text NOT NULL,
  model_at_entry double precision NOT NULL,
  entry_price double precision NOT NULL,
  gap_pts double precision NOT NULL,
  contracts integer NOT NULL CHECK (contracts > 0),
  entry_fee double precision,
  exit_condition text NOT NULL,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  exit_state text,
  exit_at timestamptz,
  exit_price double precision,
  exit_fee double precision,
  exit_reason text,
  pnl double precision,
  pnl_basis text
);

CREATE TABLE IF NOT EXISTS public.gap_runs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  taken_at timestamptz NOT NULL,
  series text NOT NULL,
  category text NOT NULL,
  open_markets integer NOT NULL,
  logged integer NOT NULL,
  one_sided_skipped integer NOT NULL,
  error text
);

CREATE OR REPLACE FUNCTION public.gap_first_pairs()
RETURNS TABLE (category text, model double precision, market double precision, outcome smallint)
LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT s.category, s.model_prob, s.mid, o.outcome
  FROM (SELECT DISTINCT ON (ticker) ticker, category, model_prob, mid FROM public.gap_snapshots
        WHERE model_prob IS NOT NULL AND mid IS NOT NULL ORDER BY ticker, taken_at) s
  JOIN public.gap_outcomes o USING (ticker)
$$;

CREATE OR REPLACE FUNCTION public.gap_funnel()
RETURNS TABLE (category text, reason text, n bigint)
LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT category, 'rows', count(*) FROM public.gap_snapshots GROUP BY 1
  UNION ALL SELECT category, 'flagged', count(*) FROM public.gap_snapshots WHERE flagged GROUP BY 1
  UNION ALL SELECT category, unnest(failed), count(*) FROM public.gap_snapshots GROUP BY 1, 2
$$;

CREATE OR REPLACE FUNCTION public.gap_unresolved(asof timestamptz, max_rows integer)
RETURNS TABLE (ticker text)
LANGUAGE sql STABLE SET search_path = public AS $$
  SELECT DISTINCT s.ticker FROM public.gap_snapshots s
  LEFT JOIN public.gap_outcomes o USING (ticker)
  WHERE o.ticker IS NULL AND s.settles_at < asof
  LIMIT max_rows
$$;

ALTER TABLE public.gap_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gap_outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gap_positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gap_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.gap_snapshots, public.gap_outcomes, public.gap_positions, public.gap_runs FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.gap_first_pairs() FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.gap_funnel() FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.gap_unresolved(timestamptz, integer) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.gap_first_pairs() TO service_role;
GRANT EXECUTE ON FUNCTION public.gap_funnel() TO service_role;
GRANT EXECUTE ON FUNCTION public.gap_unresolved(timestamptz, integer) TO service_role;

DROP TRIGGER IF EXISTS gap_snapshots_no_update ON public.gap_snapshots;
CREATE TRIGGER gap_snapshots_no_update BEFORE UPDATE OR DELETE ON public.gap_snapshots
  FOR EACH ROW EXECUTE FUNCTION public.idea_runs_append_only();
