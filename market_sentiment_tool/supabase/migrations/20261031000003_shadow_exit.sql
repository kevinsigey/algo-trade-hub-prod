-- Trading HQ step 5: a shadow day records the exit decided at its close (stop-loss, trailing, take-profit, time).
alter table public.idea_shadow_days add column if not exists exit text not null default '';
