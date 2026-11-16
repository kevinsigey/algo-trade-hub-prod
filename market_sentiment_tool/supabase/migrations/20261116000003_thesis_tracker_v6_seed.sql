-- Thesis tracker: complete the Thesis v6 seed (2026-11-16).
--
-- The original tracker seed (20261115000001) carried the four v6 sleeves,
-- the Claims A/B/C falsifiers and the tracker_config fork. Verified against
-- the adopted spec on 2026-11-16, three pieces were missing:
--
--   1. The Systematic sleeve still read live. Kevin's ruling of 2026-11-16
--      dropped the W18/T4 name and shelved the sleeve, so the row becomes
--      status 'shelved' -- a value the status CHECK did not allow; the
--      CHECK is extended rather than mislabel the row demoted or killed.
--   2. The Gray Area governor odds (stalemate 55 / boom 20 / crash 25)
--      were stored nowhere; the capex grading lines already ride in the
--      big4_capex_2027 regime row's detail. A gray_area_odds row joins
--      regime_inputs.
--   3. The section 6 dispositions for T2/T5/T6/T7/T9/T10 had no rows
--      (T1/T3/T8/T4 are carried by the sleeve rows). They are recorded as
--      disposition rows; 'none' joins the sleeve CHECK for theses that
--      have no v6 sleeve.
--
-- Data only beyond the two CHECK extensions; every insert is idempotent.

alter table theses drop constraint theses_status_check;
alter table theses add constraint theses_status_check
  check (status in ('live', 'shadow', 'demoted', 'killed', 'merged', 'shelved'));

alter table theses drop constraint theses_sleeve_check;
alter table theses add constraint theses_sleeve_check
  check (sleeve in ('core', 'systematic', 'regime', 'event_lab', 'none'));

update theses
   set status = 'shelved',
       title = 'Systematic (T4, W18) - shelved by Kevin''s ruling 2026-11-16 (W18 name dropped; sleeve not run). Its 15-20% weight is assigned to cash in full by the same ruling (no event reserve, no premium-cap change), to be revisited when automatic grading is live'
 where slug = 'systematic';

insert into theses (slug, title, sleeve, status, spec_ref) values
  ('t2-kshape', 'T2 K-Shape - killed (Thesis v6 section 6)', 'none', 'killed',
   'thesis_v6_spec_2026-11-15.md#t2'),
  ('t5-dec-fomc-santa', 'T5 Dec FOMC x Santa - Leg A killed; Leg B demoted to a calendar note (Thesis v6 section 6)', 'none', 'demoted',
   'thesis_v6_spec_2026-11-15.md#t5'),
  ('t6-oil-iran', 'T6 Oil/Iran - killed (Thesis v6 section 6)', 'none', 'killed',
   'thesis_v6_spec_2026-11-15.md#t6'),
  ('t7-intc-continuation', 'T7 INTC continuation - merged into the event lab file set; its form survives as play kind (a) (Thesis v6 section 6)', 'event_lab', 'merged',
   'thesis_v6_spec_2026-11-15.md#t7'),
  ('t9-chain-read-across', 'T9 Chain read-across - merged: promoted only as the tested form, play kind (b) in the event lab (Thesis v6 section 6)', 'event_lab', 'merged',
   'thesis_v6_spec_2026-11-15.md#t9'),
  ('t10-construction', 'T10 Construction - merged into enforced rules (sleeve caps, cash floor, sizing fork), not a thesis (Thesis v6 section 6)', 'none', 'merged',
   'thesis_v6_spec_2026-11-15.md#t10')
on conflict (slug) do nothing;

insert into regime_inputs (key, state, detail, as_of, source_note) values
  ('gray_area_odds', 'ratified',
   '{"stalemate": 0.55, "boom": 0.20, "crash": 0.25}'::jsonb,
   '2026-11-15',
   'Kevin''s ratified judgment (Gray Area paper), Thesis v6 section 1 - the governor sets Core beta vs the Regime sleeve')
on conflict (key) do nothing;
