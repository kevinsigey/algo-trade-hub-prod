-- Classic watchlist screens (Kevin, 2026-11-09 addenda): entrance/exit
-- diffing storage for screens whose spec carries membership_diff (the
-- classic three, ids 5/6/7). Two jsonb columns on the screens row itself —
-- the row already carries its record (last_run); this is the same pattern,
-- deliberately not a new table:
--   membership         {"tracked_since", "as_of", "members": {ticker: since}}
--   membership_events  [{ticker, kind, date, since?}] — append-only,
--                      bounded to the most recent 100 by the writer.
-- Both stay null for every non-diffed screen. The first diffed run
-- baselines silently (members since the baseline date, no events).
alter table public.screens add column if not exists membership jsonb;
alter table public.screens add column if not exists membership_events jsonb;
