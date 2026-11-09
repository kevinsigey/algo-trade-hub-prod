-- Gap tracker pause (Kevin, 2026-11-09): the desks' entry switch.
--
-- gap_controls is the ONE editable switch: tradehub.gaps.run reads the
-- 'global' row on every pass, so pausing or resuming entries is an UPDATE
-- here, never a deploy. Only the entry step reads it — settlement and the
-- mechanical exits never do — so positions already open when the desk
-- pauses still resolve under the existing exit rules and the paper record
-- completes honestly.
--
-- Seeded PAUSED: the pause is the point of this migration. The row lands
-- before the code that reads it, so the first pass under the new code is
-- already paused. Service role only; no anon or authenticated access.
create table if not exists public.gap_controls (
  scope text primary key,
  entries_enabled boolean not null,
  updated_at timestamptz not null default now(),
  note text
);

alter table public.gap_controls enable row level security;
revoke all on public.gap_controls from anon, authenticated;

insert into public.gap_controls (scope, entries_enabled, note)
values ('global', false,
        'Paused by Kevin 2026-11-09: no new entries on either desk (oil or crypto); open positions resolve under the existing exit rules. Resume with entries_enabled = true.')
on conflict (scope) do nothing;
