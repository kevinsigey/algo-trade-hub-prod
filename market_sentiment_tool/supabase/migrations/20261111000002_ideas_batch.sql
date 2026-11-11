-- Workshop search/batch identity (2026-11-11, A3): an idea generated as one
-- trial of a wider search carries that search on its row, so the shuffle bar
-- is raised by the trials in the batch rather than by this idea's own reruns
-- alone, and the page can say which trial of the batch it is. Nullable: an
-- idea with no batch is a single, hand-made trial and keeps the old rule.
alter table ideas add column if not exists batch_id text;
alter table ideas add column if not exists batch_trial int;

-- Backfill, only where the record already proves the batch (Kevin approved
-- 2026-11-11): the four Spec E siblings, titled Spec E-1: .. Spec E-4:.
update ideas
set batch_id = 'spec-e',
    batch_trial = substring(title from '^Spec E-([0-9]+):')::int
where title ~ '^Spec E-[0-9]+:' and batch_id is null;

-- Random Lab Gen 3 survivors: each plain_words ends with its lab trial
-- number ("Random Lab Gen 3 trial 54.").
update ideas
set batch_id = 'random-lab-gen-3',
    batch_trial = substring(plain_words from 'Random Lab Gen 3 trial ([0-9]+)')::int
where plain_words like '%Random Lab Gen 3 trial %' and batch_id is null;

-- Random Lab Gen 2 survivors: their plain_words name the generation but
-- carry no trial number, so the batch is recorded and the trial stays null
-- rather than inventing one.
update ideas
set batch_id = 'random-lab-gen-2'
where plain_words like '%Random Lab Gen 2%' and batch_id is null;
