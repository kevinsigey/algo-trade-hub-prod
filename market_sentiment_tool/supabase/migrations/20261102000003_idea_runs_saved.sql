-- Workshop runs, save-by-choice (Kevin, 2026-11-02): a run is an ephemeral preview
-- until it is saved. Only saved runs count -- toward the public record, the Workshop
-- list's latest verdict, tracking, and the live gate.
--
-- idea_runs is append-only (its trigger refuses every update), so saving cannot be a
-- column on the run: it is its own insert. A run is saved iff a row exists here.
-- Existing runs are grandfathered as saved (under the old rule, running WAS
-- recording), stamped with the run's own creation time; new runs simply have no row.
create table if not exists public.idea_run_saves (
  run_id bigint primary key references public.idea_runs(id),
  saved_at timestamptz not null default now()
);

insert into public.idea_run_saves (run_id, saved_at)
  select id, created_at from public.idea_runs
  on conflict (run_id) do nothing;

alter table public.idea_run_saves enable row level security;
