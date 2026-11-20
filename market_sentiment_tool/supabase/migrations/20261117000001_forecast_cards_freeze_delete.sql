-- Forecast cards: extend the freeze trigger to DELETE.
--
-- 20261115000001_thesis_tracker.sql froze forecast_cards against
-- UPDATE only; the freeze function already raises unconditionally,
-- so a DELETE would silently remove a frozen card. Recreate the
-- trigger over UPDATE OR DELETE (the house pattern, cf.
-- paper_order_checks). Claude's cleanup item; Kevin's go given
-- 2026-11-18 (issue #524, comment 6990638900).

drop trigger if exists forecast_cards_no_update on public.forecast_cards;
create trigger forecast_cards_no_update
  before update or delete on public.forecast_cards
  for each row execute function public.forecast_cards_freeze();
