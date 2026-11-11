-- Order attribution (2026-11-11): the stated reason a discretionary machine
-- order exists. The machine API refuses placements that carry neither an
-- idea_id nor a reason; the reason is stored on the order's label row so
-- Portfolio results can split tested ideas from discretionary trades with
-- their reasons attached. Nullable: every historical label row has none.
alter table order_labels add column if not exists reason text;
