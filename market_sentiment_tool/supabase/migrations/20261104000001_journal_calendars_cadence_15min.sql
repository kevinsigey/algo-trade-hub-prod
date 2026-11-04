-- The '15min' cadence (PR #370, the 15-minute direction family) shipped in
-- code -- contract.CADENCES, scoring.MIN_SETTLED, the frontend types -- but
-- the journal_calendars check was not widened, so every calendar insert for
-- the family was rejected with 23514, the runner recorded a per-forecaster
-- failure, and the family froze nothing. This is the second time this exact
-- trap fired (the hourly family, 2026-11-01, see 20261102000001).
-- tests/test_cadence_parity.py now pins the constraint to the code's set.

alter table public.journal_calendars
  drop constraint journal_calendars_cadence_check;

alter table public.journal_calendars
  add constraint journal_calendars_cadence_check
  check (cadence = any (array['daily', 'weekly', 'monthly', 'meeting', 'hourly', '15min']));
