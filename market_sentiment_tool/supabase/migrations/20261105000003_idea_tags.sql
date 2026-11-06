-- Kevin's own groupings for the Ideas page (2026-11-05): free-form tags on an idea, set from the Workshop.
-- The ideas table already has RLS on; this adds one column and changes no policy.
alter table public.ideas add column if not exists tags text[] not null default '{}';
