# Applied migrations

The authoritative record of which `market_sentiment_tool/supabase/migrations/*.sql` files have been
applied to the production Supabase project.

**Confirmed by Kevin on 2026-10-17: every migration listed below is applied.** The newest (the
watermark) is `20260428000021_journal_scores_paired_brier_validate.sql`.

## Why this file exists

A migration and the code that reads it ship in the same PR, but they are applied at different times by
different people. `tradehub/journal/store.py` is the clearest example of why that is not a formality:
it carries explicit fallbacks for migration `20260428000018` (`journal_forecasts.horizon_seconds`) and
`20260428000020` (`journal_scores.brier_on_baseline` / `n_baseline`), because PostgREST rejects the
*whole* insert when it names an unknown column. Get that order wrong and the journal silently records
nothing while every scorecard keeps its last value — nothing looks broken.

`tests/test_migrations_recorded.py` fails any PR that adds a migration file without recording it here,
so applying a migration is a deliberate, dated act by a person rather than an assumption.

## Applied, in filename order

| # | Migration |
|---|---|
| 1 | `20260223183727_init_trading_schema.sql` |
| 2 | `20260223183729_6cd04bce-991f-481b-8fe4-918f9bb0fc76.sql` |
| 3 | `20260223223000_enable_realtime_and_rls.sql` |
| 4 | `20260408224000_crypto_operator_plane.sql` |
| 5 | `20260415090000_signal_events_unification.sql` |
| 6 | `20260416000000_schema_consolidation.sql` |
| 7 | `20260416000001_kalshi_edges_and_macro.sql` |
| 8 | `20260416000002_pgvector_news.sql` |
| 9 | `20260416000003_predictions_ledger.sql` |
| 10 | `20260416000004_backtest_runs.sql` |
| 11 | `20260416000005_kalshi_edges_urls_energy.sql` |
| 12 | `20260416000006_backtest_log_loss.sql` |
| 13 | `20260416000007_predictions_hardening.sql` |
| 14 | `20260416000008_sports_reviews.sql` |
| 15 | `20260416000009_jobs_scorecard.sql` |
| 16 | `20260416000010_rls_portfolio_news.sql` |
| 17 | `20260416000011_war_room_tables.sql` |
| 18 | `20260428000012_kalshi_quarantine_edges.sql` |
| 19 | `20260428000013_signal_events_publication_and_rls.sql` |
| 20 | `20260428000014_prediction_journal.sql` |
| 21 | `20260428000015_journal_costs.sql` |
| 22 | `20260428000016_journal_backtests.sql` |
| 23 | `20260428000017_journal_backtests_uncertainty.sql` |
| 24 | `20260428000018_journal_forecasts_horizon.sql` |
| 25 | `20260428000019_journal_forecasts_horizon_validate.sql` |
| 26 | `20260428000020_journal_scores_paired_brier.sql` |
| 27 | `20260428000021_journal_scores_paired_brier_validate.sql` |
| 28 | `20260428000022_journal_scores_gap.sql` |
| 29 | `20261029000001_journal_previews.sql` |
| 30 | `20261030000001_portfolio_snapshots.sql` |
| 31 | `20261030000002_workshop.sql` |
| 32 | `20261031000001_ideas_live.sql` |
| 33 | `20261031000002_paper_orders.sql` |
| 34 | `20261031000003_shadow_exit.sql` |
| 35 | `20261101000001_api_keys.sql` |
| 36 | `20261101000002_run_diagnostics.sql` |
| 37 | `20261102000001_journal_calendars_cadence.sql` |
| 38 | `20261102000002_ideas_tracking.sql` |
| 39 | `20261102000003_idea_runs_saved.sql` |
| 40 | `20261102000004_geo_snapshots.sql` |
| 41 | `20261102000005_book_activations.sql` |
| 42 | `20261102000006_manual_actions.sql` |
| 43 | `20261102000007_screens.sql` |
| 44 | `20261102000008_deal_runs.sql` |
| 45 | `20261103000001_oil_itm_lines.sql` |
| 46 | `20261103000002_dune_series.sql` |
| 47 | `20261103000003_agent_specs.sql` |
| 48 | `20261103000004_kill_any_idea.sql` |
| 48 | `20261103000004_rls_machine_and_book_tables.sql` |
| 49 | `20261103000005_journal_frozen_counts.sql` |
| 50 | `20261103000006_paper_order_checks.sql` |
| 51 | `20261103000007_api_key_book.sql` |
| 52 | `20261103000008_idea_critiques.sql` |
| 53 | `20261103000009_gap_tracker.sql` |
| 54 | `20261103000010_gap_tracker_paging.sql` |
| 55 | `20261103000011_oil_best_strike.sql` |
| 56 | `20261104000001_journal_calendars_cadence_15min.sql` |
| 57 | `20261105000001_oil_best_strike_live_feed.sql` |
| 58 | `20261105000002_manual_moves.sql` |
| 59 | `20261105000003_idea_tags.sql` |
| 60 | `20261106000001_fifteen_min_ticks.sql` |
| 61 | `20261106000002_guidance.sql` |
| 62 | `20261108000001_valuation_bands.sql` |
| 63 | `20261108000002_order_labels_tag.sql` |
| 64 | `20261109000001_fifteen_rule_tracking.sql` |
| 65 | `20261109000002_valuation_band_basis.sql` |
| 66 | `20261109000003_oil_picker_v2.sql` |
| 67 | `20261109000004_fifteen_shadow.sql` |
| 68 | `20261109000004_valuation_phase1.sql` |
| 69 | `20261109000004_portfolio_check.sql` |
| 70 | `20261109000005_gap_pause.sql` |
| 71 | `20261109000006_band_crossing.sql` |
| 72 | `20261109000007_level_watcher.sql` |
| 73 | `20261109000008_guidance_snapshots.sql` |
| 74 | `20261109000009_screen_membership.sql` |
| 75 | `20261110000001_debate_candidates.sql` |
| 76 | `20261110000002_loop_round4.sql` |
| 77 | `20261110000003_fifteen_ticks_depth.sql` |
| 78 | `20261111000001_order_labels_reason.sql` |
| 79 | `20261111000002_ideas_batch.sql` |
| 80 | `20261111000003_fifteen_blend_shadow.sql` |
| 81 | `20261111000004_leaps_shadow.sql` |
| 82 | `20261111000005_leaps_open_pair_unique.sql` |
| 83 | `20261112000001_leaps_trial_verdicts.sql` |
| 84 | `20261112000002_kalshi_demo_orders.sql` |
| 85 | `20261112000004_fifteen_volregime_shadow.sql` (applied 2026-11-12 by Claude through the Supabase connector as `fifteen_volregime_shadow` on Kevin's go; renumbered from 000003 after a filename collision with #514, with `low95_clustered` and `paired_low95_clustered` on the evals table; read back: decisions 25 columns, weights 9, evals 14, RLS on for all three, no anon/authenticated grants, unique keys present) |
| 86 | `20261112000003_portfolio_snapshots_qqq_price.sql` (applied 2026-11-12 on Kevin's go for the QQQ benchmark in Portfolio step 6 PR 3, #514; read back: column present, 142 rows all NULL until the hourly-bar backfill that ships in the same PR. Row 86 though its filename sorts before row 85's: it was applied first, and #513 took row 85 while #514 was in review -- the watermark stays at `000004`, the newest filename) |
| 87 | `20261113000002_journal_scores_earned_weight.sql` (applied 2026-11-13 by Claude through the Supabase connector as `journal_scores_earned_weight`, connector version 20261113021745, on Kevin's go for action-plan step 9; read back: `earned_weight` jsonb, nullable, present on journal_scores. Its companion lane-key migration (the 20261113000001 file) was applied just before it (connector version 20261113021744) and is recorded with the demo-lane PR that carries its file) |
| 88 | `20261113000001_kalshi_demo_orders_lane_key.sql` (applied 2026-11-13 by Claude through the Supabase connector as `kalshi_demo_orders_lane_key`, connector version 20261113021744, on Kevin's go for action plan Step B.3; read back: `gate_version` NOT NULL (1 live row, 0 nulls), the old (series, target) key dropped, `kalshi_demo_orders_series_target_gate_key` UNIQUE (series, target, gate_version) present. Row 88 though its filename sorts before row 87's: it was applied first, and row 87's PR shipped first -- the watermark stays at `20261113000002`, the newest filename) |

| 89 | `20261113000003_kalshi_demo_orders_last_error.sql` (applied 2026-11-14 by Muse at the Supabase-to-VPS cutover, on Kevin's go of 2026-11-13 through Claude (issue #524). Applied to the NEW self-hosted VPS database only (psql over the SSH tunnel as supabase_admin, right after the full re-copy and before the writers resumed); deliberately NOT applied to the cloud project, which stays frozen as the rollback copy without this column. Read back: `last_error` text, nullable, present on `kalshi_demo_orders` in the local DB; the Kalshi runner resumed against the local DB at the same cutover) |
| 90 | `20261114000001_fifteen_binance_shadow.sql` (applied 2026-11-14 by Muse to the VPS-local database only, on Kevin's explicit go the same evening; read back: `fifteen_binance_decisions` and `fifteen_binance_evals` both exist with row security on and 0 rows. Creates both tables for the preregistered v5-binance-gold-shadow; the runner's passes are fail-soft and its reads treat an absent table as an empty record until the code lands. The cloud project was deliberately NOT applied -- it stays the frozen rollback copy. The watermark advances to this filename because the ledger test tracks the newest file on disk, not applied state) |
| 91 | `20261116000001_fifteen_binance_grants.sql` (applied 2026-11-16 by Muse to the VPS-local database only, as the defect repair completing row 90: the two shadow tables carried no service_role grant -- the cloud project's default privileges had covered it, the self-hosted stack's do not -- so the runner's PostgREST access failed with 42501, first seen in fifteen_min_run's fifteen_binance_eval pass on 2026-11-16. Grants select/insert/update/delete on both tables to service_role; anon/authenticated stay revoked per row 90's intent. Read back: service_role privileges present on both tables, and a fifteen_min_run pass completes its eval section with no 42501. The cloud project was deliberately NOT applied -- it stays the frozen rollback copy) |
| 92 | `20261115000001_thesis_tracker.sql` (applied 2026-11-16 by Muse to the VPS-local database only, on Kevin's go of 2026-11-16 for the Thesis v6 tracker build; row 92 though its filename sorts before row 91's -- the file was designed 2026-11-15 and the grants repair landed first -- and the watermark stays at `20261116000001`, the newest filename. Creates the nine tracker tables (theses, thesis_falsifiers, forecast_cards, forecast_outcomes, trade_links, tracker_config, tracker_health, research_files, regime_inputs), each with row security on, anon/authenticated revoked, and an explicit service_role grant per the row-91 lesson; the forecast_cards freeze trigger (UPDATE always raises; corrections are superseding inserts); seeds: the four v6 theses, falsifiers A/B/C armed in their spec forms (the falsifier window column is window_spec -- WINDOW is reserved), tracker_config 5000/10000/1500 with play_kind_c_live false and the 10% cash floor, and five regime_inputs rows with the 2026-11-16 states. Read back: all nine tables present, seeds exact, no table missing its service_role grant, and the freeze trigger proven in a rolled-back transaction (insert landed, UPDATE raised, rollback left 0 cards). The cloud project was deliberately NOT applied -- it stays the frozen rollback copy) |
| 93 | `20261116000002_portfolio_check_v6_remap.sql` (applied 2026-11-16 by Muse to the VPS-local database only, on Kevin's expedite ruling of 2026-11-16 pulling the v6 cap remap ahead of thesis-tracker PR 5. Rewrites the portfolio_targets 'global' row to the Thesis v6 caps, mirroring portfolio_check.DEFAULT_CONFIG as remapped in the same PR: core (index) sleeve cap 25 -> 50 pct of invested (the v6 core target of 40-45 pct of the book at the 10 pct cash floor; the 25 cap was the wall that stopped the staged core fills that morning); the T4 ballast sleeve retired outright (W18/T4 shelved -- the stored row loses the sleeve because the engine's deep-merge cannot delete one, and the code seed drops it in the same PR); XLU/XLV/XLP move to a new Regime sleeve (member cap 20, no floor, no sleeve cap); XLRE/VNQ/DBC/USO and GLD become unassigned (GLD keeps its 12 pct override); Regime single names AEP/D/JPM gain 5 pct name overrides so the single-name line holds inside the member band. Read back: t3_index sleeve_max_pct 50, no t4_ballast key in the stored config, regime member_max_pct 20, overrides GLD 12/11 + AEP/D/JPM 5. The cloud project was deliberately NOT applied -- it stays the frozen rollback copy) |
| 94 | `20261116000003_thesis_tracker_v6_seed.sql` (applied 2026-11-16 by Muse to the VPS-local database only, completing the Thesis v6 seed after a verify pass against the adopted spec found three gaps in row 92's seed. (1) The Systematic thesis still read live: it becomes status 'shelved' under Kevin's ruling of 2026-11-16 (the W18/T4 name dropped, the sleeve not run), its title recording that the sleeve's 15-20 pct weight is assigned to cash in full by the same ruling (no event reserve, no premium-cap change; revisited when automatic grading is live) -- the theses status CHECK gains 'shelved' rather than mislabel the row demoted or killed. (2) The Gray Area governor odds were stored nowhere: a gray_area_odds regime_inputs row now carries Kevin's ratified judgment (stalemate 0.55, boom 0.20, crash 0.25, as of the 2026-11-15 adoption); the capex grading lines already rode in the big4_capex_2027 row's detail. (3) The section-6 dispositions for T2 (killed), T5 (Leg A killed, Leg B demoted), T6 (killed), T7 (merged into the event lab), T9 (merged -- lives only as play kind (b)) and T10 (merged into enforced rules) had no rows: they are recorded as disposition rows, and the theses sleeve CHECK gains 'none' for theses with no v6 sleeve. Read back: 10 theses rows (core/event-lab/regime live, systematic shelved, six dispositions), gray_area_odds ratified 55/20/25, both CHECKs extended. The cloud project was deliberately NOT applied -- it stays the frozen rollback copy) |
| 95 | `20261117000002_kalshi_prod_paper_fills.sql` (applied 2026-11-17 by Muse to the VPS-local database only, on Kevin's go given the same day through Claude (issue #524, comment 6955507218); read back: `kalshi_prod_paper_fills` exists with row security on, service_role holding select/insert/update/delete, no anon or authenticated grants, and the (series, target, gate_version) unique key in place. Creates the would-have-filled record for the Kalshi demo lane: at each demo decision the runner reads the production book through the public API (GET only) and records what the real book would have done, settled once the outcome lands. Observation only -- no order path touches this table. The cloud project was deliberately NOT applied -- it stays the frozen rollback copy) |

**Watermark: `20261117000002_kalshi_prod_paper_fills.sql`**

## How to record a new one

1. Apply the migration to the production Supabase project. Agents may apply it through the Supabase connector or CLI (Kevin, 2026-11-01), and it counts as applied only after the change is read back.
2. Add a row to the table above, in filename order.
3. Update the watermark line.
4. `tests/test_migrations_recorded.py` must pass before the PR merges.
