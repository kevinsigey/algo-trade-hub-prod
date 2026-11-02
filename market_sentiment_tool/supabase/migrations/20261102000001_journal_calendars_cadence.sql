-- The journal_calendars cadence check (20260428000014) predates two forecasters:
-- claims (cadence 'weekly', first freeze window 2026-11-05) and the WTI hourly
-- family (cadence 'hourly', shipped 2026-11-01). Their calendar inserts were
-- rejected with 23514, the runner recorded a per-forecaster failure, and the
-- hourly family froze nothing at all -- invisible until the journal log was read
-- on the VPS on 2026-11-01. Widen the check to every cadence the code emits
-- (daily, weekly, monthly, meeting, hourly).

alter table public.journal_calendars
  drop constraint journal_calendars_cadence_check;

alter table public.journal_calendars
  add constraint journal_calendars_cadence_check
  check (cadence = any (array['daily', 'weekly', 'monthly', 'meeting', 'hourly']));
