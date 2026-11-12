-- Spec F LEAPS gate fix (Kevin's call, 2026-11-11, before any pair
-- opened): the first judged gate verdict for each cohort is stored once
-- and never recomputed. The nightly grade (tradehub/leaps_shadow.py,
-- persist_gate_verdicts) inserts the 'first4' row the first night the
-- frozen cohort judges (every pair closed or carrying >= 90 days of
-- marks), and the 'extension' row likewise for pairs 5-8; the Workshop
-- panel serves the stored row verbatim. Delivery on the row is the
-- pooled definition Kevin froze: sum(leaps_pnl) / sum(share_pnl).
create table if not exists public.leaps_trial_verdicts (
  id bigint generated always as identity primary key,
  idea_id int not null,
  cohort text not null,
  state text not null,
  reason text,
  mean_carry_drag_pct real,
  pooled_delta_delivered real,
  pooled_leaps_pnl real,
  pooled_share_pnl real,
  cohort_pairs int not null,
  judged_at timestamptz not null
);
create unique index if not exists leaps_trial_verdicts_idea_cohort_idx
  on public.leaps_trial_verdicts (idea_id, cohort);
alter table public.leaps_trial_verdicts enable row level security;
revoke all on public.leaps_trial_verdicts from anon, authenticated;
