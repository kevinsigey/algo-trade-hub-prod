-- One open LEAPS shadow pair per (idea, ticker), enforced in the database
-- (CodeRabbit finding on PR #483; Kevin approved 2026-11-11). The intake
-- code also handles an insert conflict by riding the crossing as an event
-- on the pair that won the race -- this index is what makes that conflict
-- surface instead of silently opening a second pair.
create unique index if not exists leaps_shadow_pairs_one_open_idx
  on public.leaps_shadow_pairs (idea_id, ticker)
  where status = 'open';
