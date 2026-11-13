-- Kalshi demo placement reliability: when a demo placement fails, the
-- runner records WHY on the order row itself (last_error), so a refused
-- placement is distinguishable on the record from an interrupted one.
-- On 2026-11-13 a claim whose creates were refused HTTP 410 (Kalshi's
-- retired V1 order endpoint) was written off at its cutoff as
-- "placement_interrupted", and the actual error existed only in the
-- runner's log. The runner writes this column best-effort (a refused
-- write no-ops) and is correct before the migration lands; the
-- watcher_alerts outbox carries the same errors in the meantime.
-- NOT APPLIED: written ahead for Kevin's go through Claude; see the
-- migrations ledger row 89.
alter table public.kalshi_demo_orders
  add column if not exists last_error text;
