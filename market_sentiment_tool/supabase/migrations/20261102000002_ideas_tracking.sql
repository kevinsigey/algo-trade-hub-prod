-- Workshop cleanup (Kevin, 2026-11-02): tracking is its own lifecycle step, separate from going live.
-- A passed idea can be tracked -- its confirmed rule is shadow-recorded day by day from tracked_at,
-- with no orders -- while the live-paper gate (63 new days + sizing) matures on its own clock.
alter table public.ideas
  add column if not exists tracked_at timestamptz,
  add column if not exists tracked_run_id bigint references public.idea_runs(id);

create or replace function public.ideas_lifecycle_once() returns trigger language plpgsql as $$
begin
  if (old.published_at is not null and new.published_at is distinct from old.published_at)
     or (old.live_at is not null and (new.live_at is distinct from old.live_at
         or new.size_pct is distinct from old.size_pct or new.live_run_id is distinct from old.live_run_id
         or new.gate is distinct from old.gate))
     or (old.tracked_at is not null and (new.tracked_at is distinct from old.tracked_at
         or new.tracked_run_id is distinct from old.tracked_run_id))
     or (old.killed_at is not null and new.killed_at is distinct from old.killed_at) then
    raise exception 'an idea is published, tracked, goes live and is killed once; that record is never changed';
  end if;
  if new.killed_at is not null and new.live_at is null then
    raise exception 'only a live idea can be killed';
  end if;
  return new;
end
$$;
