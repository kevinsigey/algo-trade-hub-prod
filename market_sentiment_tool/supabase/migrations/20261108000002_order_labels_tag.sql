-- Thesis tags on machine orders (2026-11-08): a manual machine order may carry a
-- short `tag` (the thesis / manual-action label, e.g. "gld-trim") that is stored
-- with the order's label row and surfaced on the resulting portfolio lots, so
-- manual plays stay organized by idea instead of landing unattributed.
-- order_labels already has RLS on and is append-only; this adds one nullable
-- column and changes no policy. Metadata only: nothing routes or sizes by it.
alter table public.order_labels add column if not exists tag text;
