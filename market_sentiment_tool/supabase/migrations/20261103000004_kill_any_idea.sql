-- PASS-rigor trim (Kevin, 2026-11-03): retiring an idea that no longer
-- passes under the hub-wide standard must be possible before it ever
-- trades. The lifecycle stays set-once -- a killed record is never
-- rewritten -- only the live-only clause goes.
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
  return new;
end
$$;
