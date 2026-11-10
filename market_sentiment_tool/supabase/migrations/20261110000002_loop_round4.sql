-- Loop Round 4: the print-classification store + persisted queue exclusions.
--
-- forward_file_classifications is the store behind the T1 provider
-- contract Spec C's band-crossing engine, Spec D's file_state watches and
-- the debate candidates' conjunction leg already read: rows shaped
-- (ticker, classification in {improved, intact, deteriorated}, as_of),
-- latest row by as_of wins. Writes land through
-- POST /api/v1/forward-file/classifications (machine key,
-- classifications:write scope) -- append-only, a correction is a new row.
create table if not exists forward_file_classifications (
  id bigint generated always as identity primary key,
  ticker text not null,
  classification text not null
    check (classification in ('improved', 'intact', 'deteriorated')),
  as_of date not null,
  source text,
  note text,
  recorded_by text,
  recorded_at timestamptz not null default now()
);
create index if not exists forward_file_classifications_ticker_asof
  on forward_file_classifications (ticker, as_of desc);
alter table forward_file_classifications enable row level security;

-- debate_candidate_exclusions persists the names candidate generation
-- considered and set aside, with the reason -- one row per
-- (snapshot, ticker), upserted at generation time so the queue panel can
-- serve the aggregate picture from stamped data instead of a recompute.
create table if not exists debate_candidate_exclusions (
  id bigint generated always as identity primary key,
  ticker text not null,
  snapshot_id bigint,
  reason text not null,
  computed_at timestamptz not null default now(),
  unique (snapshot_id, ticker)
);
create index if not exists debate_candidate_exclusions_snapshot
  on debate_candidate_exclusions (snapshot_id);
alter table debate_candidate_exclusions enable row level security;
