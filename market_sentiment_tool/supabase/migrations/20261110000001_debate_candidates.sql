-- Loop Batch 2 (charter workstreams 4-5): debate candidates from the
-- screening/guidance flow, and the verdict record's exhibit provenance.
--
-- debate_candidates is the queue the candidate generator writes: one row
-- per name per guidance snapshot, carrying WHY the name is a candidate
-- (its sources: recorded screen membership/entrances, its band zone, its
-- print classification) and what happened when the queue drained. It is
-- an audit trail for the debate pipeline, display-only like everything
-- in the valuation layer: no idea, book, or order table reads this.
create table if not exists debate_candidates (
  id bigint generated always as identity primary key,
  ticker text not null,
  snapshot_id bigint,
  candidate_class text not null
    check (candidate_class in ('conjunction', 'entrant', 'zone')),
  priority int not null,
  state text not null default 'pending'
    check (state in ('pending', 'rendered', 'void', 'skipped')),
  sources jsonb not null,
  detail jsonb,
  verdict_id bigint references valuation_verdicts(id),
  computed_at timestamptz not null default now()
);

create index if not exists debate_candidates_queue_idx
  on debate_candidates(state, priority, ticker);
create index if not exists debate_candidates_snapshot_idx
  on debate_candidates(snapshot_id, ticker);

alter table debate_candidates enable row level security;

-- The verdict record gains its exhibit snapshot provenance (scar tissue
-- #9: a graded dataset carries the snapshot it was graded against) and
-- the recorded candidate context that brought the name to the debate.
-- Both are facts of the render; pre-Batch-2 rows keep null, never a
-- backfilled guess.
alter table valuation_verdicts
  add column if not exists snapshot_id bigint;
alter table valuation_verdicts
  add column if not exists candidate_sources jsonb;

-- Candidate-driven renders are new trigger kinds on the verdict record.
alter table valuation_verdicts
  drop constraint if exists valuation_verdicts_trigger_check;
alter table valuation_verdicts
  add constraint valuation_verdicts_trigger_check
  check (trigger in ('on_demand', 'crossing', 'falsifier_window',
    'new_guidance', 'refresh', 'screen_entrant', 'band_zone',
    'conjunction'));
