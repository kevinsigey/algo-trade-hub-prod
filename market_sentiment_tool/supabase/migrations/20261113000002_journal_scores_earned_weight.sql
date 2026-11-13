-- Step 9 (scoreboard): the journal scorecard's earned weight -- the
-- fifteen blend's slope of the model against its baseline on contested
-- rows (baseline between 10% and 90%), for the whole settled set and
-- each chronological half -- stored beside the other paired figures in
-- tradehub/journal/scoring.py. Applied 2026-11-13 by Claude through
-- the Supabase connector on Kevin's go (connector version
-- 20261113021745); read back: column present.
alter table public.journal_scores
  add column if not exists earned_weight jsonb;
