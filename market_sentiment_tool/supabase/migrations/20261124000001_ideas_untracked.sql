-- Issue #601 (Kevin, 2026-11-24): a way to remove an old idea from tracking.
-- One set-once lifecycle column beside published_at / tracked_at / live_at /
-- killed_at: when untracked_at is set, the idea leaves the tracked set (the
-- shadow job and the weekly critic stop recording it) and leaves the standing
-- set on the Ideas record. Nothing is deleted -- runs, shadow days, labels and
-- fills keep their idea id, so historical attribution is never orphaned.
alter table public.ideas add column if not exists untracked_at timestamptz;
