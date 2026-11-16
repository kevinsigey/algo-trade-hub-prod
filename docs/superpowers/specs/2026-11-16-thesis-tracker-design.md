# Design — the Thesis Tracker (v6 joining ledger)

Written 2026-11-16 (Kevin's go 2026-11-15 via the Trading Thesis Testing
chat; design draft posted to issue #524, comment 6908279417, before this
file). Governing spec: Thesis v6, adopted 2026-11-15
(`thesis_v6_spec_2026-11-15.md` in the research folder) — one mechanism
(the guide gap), two pre-print signals graded separately, the Gray Area
regime governor, four sleeves + event lab + a 10% cash floor, and Claims
A/B/C restated to be fireable. This document is the build design for the
tracker that spec's Section 7 requires. It encodes the spec; it does not
restate or amend it.

## Why

The Fable audit of the full dossier (2026-11-14) found the system's core
hole: the pieces exist (append-only classifications store, portfolio_check
with sleeve caps, the Workshop event gate, the journal's frozen-row
scoring) but nothing joins them. Print-log grade columns sat empty so
Claim A's predecessor falsifier could never fire; kill lines fired (NVDA,
2026-11-12) with no exit review created; decisions changed files that
were never amended. This build is the joining ledger.

## What exists to join (verified on main 564ea45)

- Classifications: `forward_file_classifications` +
  `tradehub/valuation/classifications.py`, machine write route
  `POST /api/v1/forward-file/classifications`.
- Manual actions: `workshop_store.add_manual_action(supa, book, idea_id,
  kind, symbol, ...)`; band crossings already create them — the
  exit-review bridge reuses this exact path.
- Level watcher: `level_watches` / `watcher_alerts`
  (`tradehub/level_watcher.py`), Alpaca bars feed.
- Preflight: `tradehub/portfolio/portfolio_check.py` is the one engine
  behind `machine_api.validate_order`, idea activations, and the
  Portfolio page card. Its seeded config still encodes the OLD T-sleeve
  caps (T4 ballast / T2 / T3 / T8) — v6 supersedes them; the remap ships
  inside the preflight PR of this build, not before (the commissioning
  brief limits order-flow changes to the ledger's own preflight blocks,
  shipped with the rest of the ledger).
- Fills/P&L: `tradehub/portfolio/book.py` reconstructs Alpaca fills and
  tags them by client order id (`tag_fills`, FIFO `closed_trades`) — the
  trades join extends that tagging.
- Prices for grading: Alpaca daily bars (the watcher's feed); SPY is the
  excess benchmark.

## Schema — one migration, `20261115000001_thesis_tracker.sql`

Ships only on Kevin's explicit migration go, recorded in
`docs/superpowers/plans/migrations-applied.md` and applied to the
VPS-local database before the code that needs it merges.

- `theses` (slug, title, sleeve `core|systematic|regime|event_lab`,
  status `live|shadow|demoted|killed|merged`, kill_lines jsonb,
  spec_ref). Seeded with the v6 structure: Event lab (T1 rebuilt), Core
  (T3+T8 merged), Systematic (T4), Regime.
- `thesis_falsifiers` (thesis_id, claim `A|B|C`, metric, threshold
  jsonb, window jsonb, deadline, state). The claims as the spec states
  them:
  - **A** — separation >= 60% over the next 40 prints, counting only
    classifications timestamped before the first after-hours print,
    every pre-registered name included, no-trades counted as controls;
    below 60% at 40 demotes the classification engine to shadow; below
    50% on a rolling 60 kills it. Review 2027-03-01.
  - **B** — across the four 2027 hyperscaler clusters: mean
    close-to-close supplier excess <= 0, or fewer than 3 of 4 clusters
    positive, kills it; two capex cuts in one round suspends it
    immediately. Verdict due by Nov 2027.
  - **C** — the next five play-kind-(a) fires must net positive after
    costs; net <= 0 kills the form. Graded 2027-03-01.
- `forecast_cards` (ticker, thesis_id, print_at, whisper_esp,
  whisper_sign, money_flow_direction, money_flow_evidence jsonb with
  source links, guide_position, predicted_direction, opposing_case_ref,
  classification, frozen_at server-stamped). INSERT-only: a trigger
  blocks UPDATE; the write route rejects any card at or after print_at.
  A correction is a new pre-print card superseding the old; the latest
  pre-print card is the graded one.
- `forecast_outcomes` (card_id, graded_at, reaction_close, +1/+3/+5
  session returns, SPY same windows, excesses, whisper_hit,
  money_flow_hit, classification_hit). The two signals and the
  classification are graded and stored SEPARATELY, never combined.
  Written only by the grader — no manual grading path exists.
- `trade_links` (client_order_id, book, forecast_id, thesis_id,
  play_kind `a|b|c`, modal_value, opposing_case_ref, shadow). Written at
  placement; P&L read from book.py FIFO by client id, net of costs.
- `tracker_config` (unit_v2_premium 5000, unit_v2_top 10000,
  unit_fallback 1500, play_kind_c_live=false, cash_floor_pct 10) and
  `tracker_health` (last_grader_run_at, last_grader_ok). The governing
  unit is read from health: last successful grade run fresh (< 26h on a
  weekday) -> Schedule v2; stale or down -> $1,500. Automatic, no vote —
  spec Section 4 verbatim.
- `research_files` (path, thesis_id, amended_at, last_decision_at).
  Staleness = a decision logged after the last amendment; the
  scoreboard flags it (the Webull 8/15/3 case).
- `regime_inputs` (big-four 2027 capex running figure, crash-trigger
  states, the three credit lights — data-center borrowing yields,
  private-credit redemption gates, bank lending tightening — each with
  as_of and source note). Manual-entry registry maintained by the
  trading chat: no honest free feed exists for two of the three lights,
  so the panel shows state + age rather than inventing a scrape.

## Enforcement points

- **Preflight** (machine order path only, inside
  portfolio_check / validate_order): an event-lab order BLOCKS with no
  opposing_case_ref, no modal_value, risk above the governing unit, or
  a post-trade cash share under the 10% floor (exits exempt, per the
  standing exits-win ruling). Live orders with play_kind `c` are
  rejected outright while play_kind_c_live=false; the flag flips only
  on a drift-test verdict entered in the v6 amendment log.
- **Kill lines**: each thesis's kill_lines materialize as level_watches
  rows tagged with the thesis; when the watcher fires one, a bridge
  creates ONE open manual action kind=exit_review, deduped per kill
  line — the NVDA 2026-11-12 case (two kills, no review) becomes
  structurally impossible.
- **Coverage**: the grader compares covered prints (earnings calendar)
  against cards and logs a coverage failure for any print with no
  pre-print card. No-trades still grade as controls.

## Grader

New script `tradehub/scripts/thesis_grade_run.py` on the deploy
crontab after the close (the ukmto_pull precedent — no root needed).
Grades every ungraded frozen card and classified print from Alpaca
daily bars (reaction close, +1/+3/+5 sessions, excess vs SPY) and
stamps tracker_health either way, so a down grader visibly drops the
sizing unit to $1,500 through the flag.

## Scoreboard page

New page + `GET /api/thesis/scoreboard`: per claim — graded count, hit
rate with interval, falsifier countdown (prints / fires / clusters
remaining, days to deadline), state; per play kind — P&L net of costs,
hit rate; breach log (preflight blocks, cash-floor breaches, stale
files); regime panel — Gray Area grading state against the $620B /
$950B capex lines and trigger states, the three credit lights with
as_of stamps, cash-floor gauge.

## PR sequence (tests first, solo gates, CodeRabbit per the interim rule)

1. This design as a docs PR + backlog rows.
2. Migration `20261115000001` + seeds (Kevin's go).
3. Forecast cards API (freeze enforcement) + card surface.
4. Grader + health heartbeat + Claim A/C progress computation.
5. trade_links + order-schema extension + preflight blocks + v6
   sleeve-config remap.
6. Kill-line watch bridge.
7. Scoreboard API + page + regime panel + staleness flags.

## Open questions (Kevin / Claude)

- (i) Migration go for `20261115000001`.
- (ii) Regime inputs as a manual registry (above) vs attempting
  scrapers.
- (iii) Coverage calendar source — journal calendars vs a dedicated
  earnings-calendar pull.
