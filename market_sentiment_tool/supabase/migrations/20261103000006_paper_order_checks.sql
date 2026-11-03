-- What the broker finally did with each rule order, written by the post-open reconcile job.
-- paper_orders is append-only, so the answer lives beside it, and is append-only too.
CREATE TABLE IF NOT EXISTS public.paper_order_checks (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  book text NOT NULL,
  client_order_id text NOT NULL,
  broker_status text NOT NULL,
  filled_qty numeric NOT NULL,
  filled_avg_price numeric,
  checked_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (book, client_order_id)
);
ALTER TABLE public.paper_order_checks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.paper_order_checks FROM anon, authenticated;
DROP TRIGGER IF EXISTS paper_order_checks_no_update ON public.paper_order_checks;
CREATE TRIGGER paper_order_checks_no_update BEFORE UPDATE OR DELETE ON public.paper_order_checks
  FOR EACH ROW EXECUTE FUNCTION public.idea_runs_append_only();
