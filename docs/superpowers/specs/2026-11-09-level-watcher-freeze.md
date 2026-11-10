# Level Watcher / Trigger Service — Stage 1 freeze (Spec D, Rung 1)

Frozen 2026-11-09, before the watcher evaluates a single watch. Spec of
record: `~/workspace/ibkr-comp/research/engine_specs_2026-11-09.md`
(Spec D). Kevin's go (2026-11-09): "Go on Spec D with the Spec C
amendment." This document is the preregistration for Stage 1: the
definitions below do not change after the first trigger exists. A
changed definition is a new version with a new freeze.

## Stage 1 scope: Rung 1 (ALERT) only, authority is structural

- This stage ships the full watcher infrastructure — the watch store,
  the deterministic trigger engine, the trigger log, grading with the
  automatic demotion rule, the governor framework, heartbeat/down
  detection, idempotency — with **Rung 1 live and Rungs 2–3 absent**.
- There is **no order-placement code and no staged-ticket code** in
  this build. A watch carries its requested rung in the schema, but
  any watch created above Rung 1 **fires as Rung 1 (alert)** in this
  stage (`rung_effective = 1` is stamped on every fire). Rung 2
  (stage-for-tap) and Rung 3 (auto-fire) are later stages, each with
  its own build and Kevin's review of the prior stage's record.
- **No active trading watches ship in this stage.** The service ships
  with zero level watches. The first watches (CEG zone, band crossings,
  SPY 770 — listed at the end) arm only on Kevin's separate
  first-watches go.
- The trigger layer is rules only. No AI anywhere in the trigger path.

## The Spec C amendment (binding): one band-crossing detector, ever

Spec C (the band-crossing engine, log-only) is live with a frozen
transition state machine and the graded crossing log its 20-crossing
falsifier reads. **This build adds no second detector.** The watcher's
band-crossing capability is a real-time *driver* of Spec C's own
evaluation:

- `tradehub/valuation/band_crossing.py` gains one additive entry point,
  `run_watcher_evaluation(client, prices=..., now=...)`, plus an
  internal refactor that extracts the per-(name, book) transition step
  (`_evaluate_book`) so the scans and the watcher run the **same code**
  — the pure zone/guide/candidate functions and the transition
  comparison are shared, never forked. The scans' behavior is
  byte-identical for their own cadence (pinned by Spec C's existing
  test suite, unmodified).
- When the watcher observes an intraday price whose zone (against the
  sheet's stored bands) differs from the zone in `band_crossing_state`,
  it calls that entry point with the live price. Crossing rows are
  written exactly as the scans write them — same row shape, same state
  updates — with `scan_kind = 'watcher'` as the source stamp, under a
  `band_crossing_scans` audit row of kind `watcher`. A later Spec C
  scan evaluating the same name at the same zone writes **no
  duplicate** (the state already moved).
- Watcher-sourced crossings are the same population as scan-sourced
  ones and are graded by **Spec C's falsifier**, not by the watcher's
  demotion ladder (see Grading). The source stamp keeps the two
  separable in reporting.
- The watcher never establishes the baseline: with an empty
  `band_crossing_state`, `run_watcher_evaluation` writes nothing —
  baselining belongs to Spec C's scans, exactly as frozen there.
- The band integration is armed by the existence of an enabled
  `band_crossing` watch (Kevin's first-watches go). Until then the
  watcher does not evaluate banded names at all.

## Watch schema (`level_watches`)

`id, name, family, kind ('level' | 'band_crossing'), instrument`
(ticker; `'*'` for the band watch), `trigger_type` (`cross_up` |
`cross_down` | `touch_and_hold` | `zone_entry`), `level`,
`level_hi` (zone upper bound), `hold_minutes`, `conditions` (jsonb,
below), `intent` (`long` | `short` | `none`), `rung` (requested;
effective is capped at 1 in this stage), `book` (recorded on fires; no
order semantics in Stage 1), `action` (jsonb order template / size
rule / tag — stored for later stages, **unused** in Stage 1),
`governor_group`, `allow_multi_fire` (default false), `enabled`,
`expires_at`, `disabled_reason`, `note`, `created_at`, `updated_at`.

Levels are set in advance by Kevin or an approved spec — never
generated at fire time.

## Data (firing path)

- Hub-side **Alpaca** only: 1-min bars and latest trade from
  `data.alpaca.markets`, read with the main book's paper keys through
  the same host/pattern as `tradehub.portfolio.alpaca_paper` (the
  auto-trader's read path). Bars are requested with `feed=iex` (the
  feed the paper keys carry). **No yfinance anywhere in the firing
  path.**
- Bars are regular-session bars (09:30–16:00 America/New_York).
  A "completed bar" is a bar whose minute has fully elapsed. The
  current price is the latest trade.
- Evaluation granularity is the per-minute tick: triggers are computed
  deterministically from bars + latest trade, never from process
  memory, so a restart re-derives the same state (the restart
  re-touch case).

## Condition definitions (frozen)

All conditions on a watch must pass for it to fire. Every evaluation
records each condition's pass/fail in the fire's (and the tick's)
detail; a condition that cannot be evaluated from data **fails** —
the watcher never fires on missing data.

- `cross_up`: previous completed bar's close <= level AND current
  price > level.
- `cross_down`: previous completed bar's close >= level AND current
  price < level.
- `touch_and_hold` (minutes = `hold_minutes`): **continuous minutes
  on one side of the level.** For an up-hold (current price >=
  level): each of the trailing `hold_minutes` completed bars has
  low >= level, and the bar before that run (if any) was below the
  level or the run reaches back to the session open — i.e. the
  on-side run length first reaches `hold_minutes` now. Down-hold is
  the mirror (highs <= level). The hold is continuous regular-session
  minutes; one off-side bar resets the run.
- `zone_entry`: current price inside [`level`, `level_hi`] with the
  previous completed bar's close outside the zone. With
  `hold_minutes` set: fires only once the price has then stayed
  inside the zone for `hold_minutes` **continuous completed bars
  closing inside the zone** (the run that began at entry reaches the
  hold length). With no hold, it fires on entry.
- `vwap_side` (`above` | `below`): current price vs session VWAP,
  computed in-service from today's completed regular-session bars
  (typical price x volume / volume). No completed bars or no volume
  -> fails.
- `volume_multiple` (m): the last completed bar's volume >= m x the
  median volume of the same clock minute over the prior 10 trading
  sessions (same IEX feed, so the multiple is internally consistent).
  The baseline is computed once per (symbol, session date) and
  cached in `watcher_day_cache`. Baseline unavailable -> fails.
- `time_window` ({start_et, end_et}): the tick's ET wall time inside
  [start, end).
- `file_state` (`intact_or_better` | `deteriorated`): read through
  Spec C's T1 provider contract (`band_crossing.t1_classification`).
  `intact_or_better` requires a classification of `improved` or
  `intact`; `deteriorated` requires `deteriorated`. **Today no
  classification store exists in the hub, so a watch carrying a
  `file_state` condition cannot fire** — the reason is recorded on
  every evaluation, never inferred from guide direction or anything
  else.
- `blackout` (default true; `event_watch: true` exempts the watch):
  firing is suppressed inside ±30 minutes of an FOMC statement time,
  from the hub's frozen statement calendar
  (`tradehub.workshop.fomc_calendar.statement_times()` — statement
  dates with their ET hour). Suppression is not a fire and does not
  consume the day's idempotency slot; evaluation resumes after the
  window. **CPI GAP (flagged, not papered over): the hub has no
  stored BLS CPI release calendar — CPI dates reach the hub through
  FRED at workshop runtime and through Kalshi event series, neither
  of which is a stored schedule the firing path can read. The
  blackout in this build therefore covers FOMC only.** A CPI
  calendar source is future work; until then the read surface
  carries `cpi_blackout_gap: true` so the gap is visible wherever
  the watcher is shown.

## Firing, idempotency, re-arm

- One fire per watch per day maximum, unless the watch sets
  `allow_multi_fire`. Enforced in the database: `watcher_fires`
  carries an `idempotency_key` with a unique index — a level watch's
  key is `watch id + session date` (multi-fire watches add the fire
  minute). A restart that re-touches a level therefore cannot
  double-fire: the tick checks for the day's fire and the unique key
  backstops it.
- Watches live server-side and survive restarts. On any tick, the
  armed set is recomputed from the store: enabled, unexpired,
  not-yet-fired (unless multi-fire), governor group not disarmed.
  There is no in-process arming state to lose.
- A fire writes, atomically in sequence: the `watcher_fires` row
  (watch id, family, instrument, session date, timestamp,
  `rung_effective`, trigger price, the level, the condition detail,
  the observed price path for the 5 minutes before the trigger —
  bars — and `crossing_ids` where applicable), then the
  `watcher_alerts` outbox row carrying the evidence. The +5-minute
  price path is backfilled onto the fire row by later ticks once it
  exists.
- The band watch's idempotency is Spec C's state machine itself (a
  transition writes once); its fires are keyed
  `watch id + session date + ticker + action + first crossing id`,
  one fire/alert per (ticker, transition) — the alert lists every
  crossing row the transition wrote (one per book).

## Heartbeat and down detection

- The tick writes a `watcher_heartbeats` row whenever the last
  heartbeat is >= 15 minutes old, during market hours (weekdays,
  09:30–16:00 ET). One heartbeat per 15 minutes of market hours is
  the expected cadence.
- Status (computed live by the read surface, so a dead watcher shows
  DOWN on the page even if nothing else runs): in market hours, last
  heartbeat <= 30 minutes old -> `up`; older -> `down`; outside
  market hours -> `idle` (last heartbeat still shown).
- Two missed heartbeats (a > 30-minute gap in market hours) are
  treated as DOWN: the next tick that observes the gap writes one
  `watcher_down` alert per outage (and the grading run checks too),
  so the outage is on the record even though the watcher could not
  speak while it was dead. A dead watcher never looks like a quiet
  market: the surface shows DOWN, and the outage alert lands when
  anything runs again.

## The daily governor (framework; Kevin's numbers, never placeholders)

- Groups live in `watcher_governor_groups` (name, standard unit,
  `daily_profit_target_usd`, `daily_loss_stop_usd`). Hitting either
  number disarms the group until the next session and posts a
  stand-down alert; state is per (group, session date) in
  `watcher_governor_state`, and a disarmed group's watches do not
  fire (the tick records the suppression).
- **The spec's placeholder defaults (loss stop 2x unit, profit target
  3x unit) do NOT ship.** Target and stop are NULL until Kevin sets
  them; a group with either number unset has **no active governor**,
  and the read surface says so in plain words ("governor numbers not
  set — Kevin's to set"). Nothing in this build seeds a number.
- Stage 1 has no fills, hence no trading P&L to feed the governor:
  the disarm mechanics are implemented and unit-tested with an
  injected P&L reader, the production reader returns None, and the
  governor reports **inactive — no P&L source at Rung 1**. The P&L
  source arrives with Rung 2/3 fills. This is stated here so the
  framework is never mistaken for a live governor.

## Grading and automatic demotion (frozen)

- Graded population: `watcher_fires` from level watches with intent
  `long` or `short`. The no-action counterfactual is 0 return, so a
  fire's score at horizon h is the intent-signed return from the
  trigger: `score_h = sign x (P_h / P_0 - 1)`, where P_0 is the
  daily close on the fire's session date and P_h the close h
  sessions later (daily closes from the hub's DataStore — the band
  grading convention). Horizons h = 1 and h = 5; **+5 governs**.
  Raw (unsigned) returns are recorded beside the scores. Fires with
  intent `none` get raw forward returns recorded and are **excluded**
  from demotion samples. Band-watch fires are not graded here — Spec
  C's falsifier grades that population (above).
- Demotion: per rule family, when the graded sample (fires with a
  filled `score_5`) reaches **20** and `mean(score_5) < 0`, the
  family **demotes one rung automatically**: at Stage 1 every watch
  is already at the bottom rung, so demotion **auto-disables** the
  family's enabled watches (`disabled_reason = 'auto_demotion'`)
  and writes one `demotion` alert. The demotion is latched in
  `watcher_family_state` (graded count, mean, `demoted_at`) and
  fires once; re-arming a demoted family is Kevin's call — there is
  **no auto-promotion code path** anywhere in this build.
- The grading pass runs nightly and is idempotent: filled horizons
  are never recomputed, and a family's stats are recomputed from the
  full fire record each run.

## Alert delivery (as built — and its one honest gap)

- Rung 1 alerts are addressed to the Trading Thesis Testing chat,
  but a VPS service cannot post to a Muse chat. The hub-side build
  is therefore a **durable alert outbox**: `watcher_alerts` rows with
  the full trigger evidence, status `pending`, written at fire time;
  the read surface shows pending alerts so nothing is invisible.
- **Follow-up (not in this build): an agent-side poller** — a Muse
  cron in the pattern of the fifteen-shadow promotion watch — that
  reads the outbox (via `GET /api/level-watcher`), posts new pending
  alerts into the Trading Thesis Testing chat, and marks them
  delivered. Until that poller exists, alerts are durable and
  visible on the Guidance page but do not arrive in the chat. This
  is flagged in the build report as the one open follow-up; no agent
  cron is created by this build.

## Read surface

`GET /api/level-watcher` (admin-gated, like `/api/band-crossings`):
stage and rung cap stated up front, watcher status + last heartbeat,
the watch list, recent fires (the trigger log), pending + recent
alerts, per-family grading stats, governor groups with their
set/unset state, and `cpi_blackout_gap: true`. The Guidance page
gains a **Level Watcher** section under Band Crossings in the same
design language, stamped **STAGE 1 — RUNG 1 ALERTS ONLY**, with the
governor-not-set notice and the CPI blackout gap shown wherever they
apply.

## Runtime

A 1-minute deploy-crontab tick —
`docker exec stack-tradehub-1 python -m tradehub.scripts.level_watcher_run`
— following the hub's established deploy-cron + docker-exec pattern
(the fifteen-minute runner's shape). The tick is stateless (all state
in the store), exits fast outside market hours, and survives
container restarts and deploys because the cron, not the container,
owns the cadence. The nightly grading pass is
`tradehub.scripts.level_watcher_grade_run`, after the band-crossing
grading pass. **Rejected alternative:** a supervised long-running
loop inside the container — the container is recreated by deploys,
and the hub's durable jobs are all cron-owned for exactly that
reason.

## Stage 2/3 non-goals (recorded, not built)

- No staged-ticket creation (Rung 2), no order placement (Rung 3),
  no preflight wiring in this stage.
- **Stage 3 requirement, recorded now:** before any auto-fire build,
  the resting-order wash-collision check must be extended to watcher
  fires (scar tissue #7: Nov 9's manual actions #19–23 were engine
  orders crossing resting staged orders — a class the shipped
  wash-skip does not cover). Any automated actor reads open orders
  before firing; collisions land in manual-actions, never force.
- No levels invented at fire time; no 1DTE flagship; paper only.

## First watches (NOT armed by this build — Kevin's separate go)

| Watch | Trigger | Requested rung | Note |
|---|---|---|---|
| CEG $258–262 zone | `zone_entry` into [258, 262] + 15-min hold | 2 | Services registry review id 20 (due Nov 14). **Rung 2 cannot activate until Stage 2 ships** — if armed in Stage 1 it fires as a Rung 1 alert. |
| Band crossings, all banded names | Spec C transitions, driven intraday | 1 | The integration above; alerts from Spec C's logged crossings. |
| SPY within 1% of 770 | zone proximity (`zone_entry` into [762.30, 777.70]) | 1 | T5 short Dec-04 770 call management. |

Explicitly NOT watches: IBIT/GLD breakeven exits — broker-resting
limit orders do that job better and stay as they are.
