# Trading system phase 3 — the reading layer + weather ens-v2 (design)

Status: DRAFT for Kevin's review, 2026-11-01. Concepts approved in chat
2026-11-01 ("Concepts are right — spec in your order"); this document is the
reviewable form. Nothing here is built by the act of writing it.

## 0. Framing

Phase 2 made the hub a trading system (machine API, Workshop, ideas, inputs).
Phase 3 is about **reading it**: several pages bury their main idea under a long
scroll, one page (weather) pairs a list layout with a model that is measurably
behind its market, and one page (crypto) presents a grader for a worker that no
longer exists. The phase also carries the one model upgrade with a measured
case behind it: weather ens-v2.

Standing principles, carried from phases 1–2 and Kevin's Nov 1 direction:

- **Summary first, detail on click.** The biggest idea leads; everything else
  is one interaction away, never deleted and never the first screen.
- **Honesty rules do not move.** A missing read renders as missing, never as
  zero or "fine"; a display-only surface never dresses itself as an edge;
  LLM/research content is labelled what it is; minimum-sample language
  (`EARLY_N = 30`) applies to every new grade shown.
- **Models are promoted on grades, not arguments.** New forecasters freeze
  beside the incumbents under new version names; the old scorecards are never
  rewritten.
- One PR per numbered step; each step is independently shippable and leaves
  the site coherent if the phase stops there.

Build order (Kevin's approved order): §1 Macro → §2 Health → §3 Weather
(map, then ens-v2) → §4 Sports → §5 Crypto → §6 reading-comfort remainder.

## 1. Macro predictions dashboard (new /macro)

**What.** Jobs and CPI stop being two long pages a visitor must scroll to
understand and become cards on one dashboard. Each card states the engine's
main idea in one glance; the existing pages become the click-through detail,
unchanged underneath.

**Cards at launch:** Jobs (labor_nowcast), CPI (cpi_nowcast), Gas (the
journal's AAA-gasoline forecaster family — it has a live journal record and
no display page today, so the dashboard is its first surface).

**Card anatomy** (per engine):
- Header: engine name + what it predicts in plain words ("Next nonfarm
  payrolls print", "Next CPI release", "AAA gas price direction") + the
  next-release countdown (the existing NextRelease data).
- The call: our current number/probability, the market's (Kalshi), and the
  last actual — three values, labelled, with as-of times.
- The record: settled n, our Brier vs the market's on the same prints
  (paired, from the journal/scoreboard reductions), the gate chip, and the
  §6.1 diagnostics flags when the newest run carries any.
- A compact trail: last ~8 prints, us-vs-market-vs-actual dots (the
  ReportDumbbells visual language already in the repo).
- Whole card links to the detail page (/jobs, /cpi; gas links to its journal
  family view until/unless it earns a page).

**CPI honesty clause.** The CPI nav label was deliberately "CPI Display"
because the board must not read as a board of opportunities. The macro card
inherits that: it shows the nowcast and the record, uses the word "display"
in its sub-line, and carries no edge/gap language. Jobs keeps its language;
the two cards must not be visually copy-pasted into implying the same claim.

**Data.** One new thin endpoint, `GET /api/macro`, composing what already
exists (scoreboard current runs, jobs-scorecard payload, journal family
summaries, release calendar). No new forecasting, no new storage. A card
whose source fails renders "unavailable" in that card only.

**Nav.** "Jobs nowcast" and "CPI Display" entries are replaced by one
"Macro predictions" entry; /jobs and /cpi routes remain as the detail pages.

## 2. Health heatmap

**What.** The Health page leads with a heatmap instead of three stacked
lists: one screen, colour first, numbers on hover, readable in seconds.

**Grid.** Rows = the tracked timers (scan, settle, journal, orderbooks) plus
one row per forecaster family; columns = the last 14 days (CT). A cell is:
- green — ran/froze as expected that day;
- amber — ran late or below its expected count;
- red — silent when it was expected (the existing calendar-aware expectation
  logic decides "expected"; a day with no expectation is grey, not green);
- the cell's intensity scales with the day's frozen count for family rows.
Hover (and keyboard focus) shows the exact counts, the day's problems, and
the last-success time. The §6.1 diagnostics become one additional row
(flags that day = amber, named on hover; still never a "problem").

**Data.** `collect_health` gains a `history` block built from bounded reads
(scanner_runs and journal tables, 14-day window). The existing point-in-time
sections (timers, families, problems, diagnostics) stay below the heatmap,
collapsed by default except Problems when non-empty. Health semantics do
not change: the heatmap visualises the same verdicts, it does not invent
new ones.

## 3. Weather — map page, then ens-v2

### 3.1 The map page (presentation; ships before the model work)

**What.** /weather becomes a Weather-Channel-style US map. One marker per
forecast city (the stations the journal actually forecasts: highs, lows,
rain). A marker shows the city's headline call for the day (e.g. the most
likely high bucket / rain probability). Hover or click opens a card for
that city:
- today's high / low / rain probabilities from the ensemble, the Kalshi mid,
  and climatology, side by side;
- the ensemble mean and spread for the temperature calls;
- that station's settled record (paired Brier vs the market, n, from the
  journal payloads);
- a link expanding that city's settled history (the list that is today's
  whole page, demoted to where it belongs).

**Implementation notes.** Hand-rolled SVG (no new map dependency): a
vendored simplified US outline (public-domain source, credited in the file)
with markers placed by the stations' known lat/lon. Cities without an
ensemble freeze still appear when Kalshi prices them, with the card saying
the ensemble has no read there — coverage gaps stay visible, they are part
of the story. The degree-day demand panel (§5.3) stays on the page below
the map — it is regional and belongs with the map. A new grouped endpoint
`GET /api/weather/map` serves per-city summaries built from journal
forecast payloads (the current /api/weather strips payloads the map needs);
the old endpoint stays for compatibility.

**Fallback.** On narrow screens the map stacks above a city list with the
same cards — the map is an enhancement, never the only path to the data.

### 3.2 ens-v2 — the model upgrade (the measured case)

**The record it answers** (live journal scores, 2026-11-01): ens-v1 paired
Brier gaps vs the Kalshi mid of +0.095 (highs), +0.062 (lows), +0.072 (rain)
at 3.5–7 standard errors; reliability buckets overconfident (80–90%
predictions realise 67–74%); simulated P&L negative in all three families.
Named defects: fixed 2.0°F smoothing kernel set before any result was seen,
no bias correction, members pooled unweighted (ECMWF outweighs GEFS 51:31).

**ens-v2 design** (the Oct 8/18/22 plans' design, restated as buildable
steps; each its own PR):
1. **Per-station bias correction + learned kernel width**, fitted
   walk-forward on settled journal pairs plus Open-Meteo previous-runs
   hindcasts; minimum history before a station's correction activates
   (below it, the station runs uncorrected and says so in its payload).
2. **Member weighting by model** instead of by headcount, and the wider
   ensemble shelf behind the same endpoint (GEFS 0.25°, ECMWF AIFS ens,
   ICON EPS, GEM ens), each model's members weighted as a bloc.
3. **A calibrated blend forecaster** as its own journal row (the existing
   calibrated/shrunk machinery): probability = fitted blend of the
   ensemble and the Kalshi mid. It freezes beside ens-v1 and ens-v2 raw;
   it never replaces anything silently. (This is the journal-level blend
   under the Oct 18 protocol; it does not wait on the backtest market-blend
   study, PR #172, which remains Kevin's separate call.)
4. **Coverage expansion**: stations from Kalshi's tradable US list
   (~20 high cities vs 4 today; lows likewise), then rain migrated from
   the 8-city umbrella mapping to the per-city KXRAIND* series (29 cities)
   with precip-quantile probabilities replacing the single 0.005″
   threshold.

**Promotion rule.** ens-v2 is judged after ≥200 newly settled contracts per
family on paired Brier vs ens-v1 AND vs Kalshi, reported on the scoreboard
like every engine. The Weather page's headline probabilities switch to
ens-v2 only on Kevin's call after that grade; until then the map labels
which model a number came from. Snow (Kalshi's KXSNOW* family) is noted as
a winter follow-on, not part of this phase.

## 4. Sports dashboard

**What.** /sports leads with predictions, in the predictor estate's own
design language (the Sports Predictor design pack the hub homepage shipped
Nov 1: Kalshi-style cards, one big probability, model-vs-market meter,
footer with model + lock time). The grading desk stays — as the second tab.

**Tabs.** "Predictions" (default) and "Grading desk" (today's edges board,
unchanged). Predictions tab:
- NFL and CFB cards from the hub's own edges data, reframed honestly: the
  card's headline is the model's probability for the featured pick, the
  meter shows model vs market, and the card links straight to the sport's
  site (https://sports.40-160-91-131.sslip.io/?sport=nfl / ?sport=cfb).
  A pick the reviewer flagged stays flagged on its card — the dashboard
  does not launder the grading desk's cautions.
- Estate cards for Premier League, NBA, and F1: the sport's current top
  prediction where the predictor site exposes one, otherwise a clean
  link card (name, what the site predicts, its record line where the
  predictor homepage already computes one) linking to
  https://pl.40-160-91-131.sslip.io, https://nba.40-160-91-131.sslip.io,
  https://f1.40-160-91-131.sslip.io. No new cross-service scraping: cards
  use the same predictor APIs the predictor homepage already consumes, via
  a small server-side read on the trade-hub backend; a sport whose API
  fails degrades to the link card, never to a blank or a stale number
  presented as live.
- Performance appears only inside each sport's section (the predictor
  homepage's own rule from Nov 1), not on the all-sports view.

## 5. Crypto research desk

**The finding this answers.** /crypto (and /shadow) render a grading
timeline for a signal worker whose flow stopped 2026-06-02; the API
returns empty at every window; nothing on the page says so; the worker
never executed (23,150 signals, all execution-skipped, demo API). The page
is retired as a grader and rebuilt as a research desk.

**The new /crypto, top to bottom:**
1. **Status line, plain:** what this page is (crypto research), and the
   sniper's state ("signal worker stopped 2026-06-02 — record below").
2. **On-chain pulse** — the existing live strip, unchanged, kept at top.
3. **The sniper's verdict:** the archived 23,150 signals (Apr–May 2026)
   re-graded once by the existing evaluator over their full window — hit
   rate, shadow-timeline Brier, dead-zone share, by coin — presented as a
   closed record with its dates on it. Not a live number, never refreshed
   as if it were.
4. **Kalshi crypto board:** the hourly KXBTCD / KXETHD markets (and the
   15-minute series shown as data) as *tracked markets* — current implied
   probabilities beside spot — labelled market data, not our predictions.
   Read through the hub's existing Kalshi client; dollar-quote fields
   handled by the existing quote-unit code.
5. **Research items:** cards for open crypto questions, each with a
   question, a status, and a result when measured. First item, pre-loaded:
   **the venue lead-lag measurement** (does the Kalshi implied probability
   move before or after spot/BRTI?) — the measurement the Sep 29 journal
   design required before any "BTC daily direction" forecaster may be
   proposed. A forecaster proposal may only appear as a later research
   item citing that measurement.

**Removals.** The ShadowBacktester UI is deleted and /shadow redirects to
/crypto (the /crypto route stays). The backend grading module remains —
the re-grade in step 3 uses it. Nav label becomes "Crypto research".

## 6. Reading-comfort remainder (absorbs phase-2 §4.4's page pass)

Scoped small, after §§1–5, each its own PR:

- **Workshop idea detail** (the deepest page on the site): a summary header
  (verdict, latest run's headline stats, lifecycle state) pinned at top;
  runs, debates, and history become collapsed sections, newest first.
- **Portfolio**: the Strategy HQ strip already leads; closed positions and
  older history collapse behind their headers. No data changes.
- **Journal**: acceptable as-is (tabbed); only change is the settled list
  gains the same per-family grouping the scoreboard uses. Optional if the
  phase runs long — named here so skipping it is a decision, not an
  oversight.
- **Timestamps/money**: one CT timestamp style and one money format across
  the pages touched by §§1–5 (the format helpers exist; this is applying
  them consistently, not new design).

Retiring the legacy backend and the README/SYSTEM_ARCH rewrite from
phase-2 §4.5 are **not** in this phase: the legacy retirement is destructive
and gets its own proposal; the docs rewrite lands better after phase 3's
surfaces exist. (SYSTEM_ARCH still gets its per-step factual updates as
each step ships, as in phase 2.)

## 7. Sequencing and dependencies

| Step | Contents | Depends on |
|---|---|---|
| 1 | /api/macro + Macro dashboard + nav change | — |
| 2 | Health history block + heatmap | — |
| 3a | /api/weather/map + map page (labels ens-v1 numbers as ens-v1) | — |
| 3b | ens-v2 step 1–2 (bias/kernel, member weighting + shelf) | 3a not required; parallel-safe |
| 3c | Blend forecaster row | 3b |
| 3d | Coverage expansion + rain per-city migration | 3b |
| 4 | Sports predictions tab + estate cards | — |
| 5 | Crypto research desk (re-grade script, board, research cards; backtester removal) | — |
| 6 | Reading-comfort remainder | §§1–5 landed |

Weather promotion (page switching to ens-v2 numbers) is a separate,
grade-gated decision after step 3b/3c settle ≥200 contracts per family —
it is not a step in this table.

## 8. Explicit non-goals

- No new trading capability, no order-path changes, no machine-API changes.
- No crypto *execution* or live crypto forecaster (see §5: measurement first).
- No deletion of detail data anywhere; every redesign demotes, never drops.
- The backtest market-blend study (PR #172) is untouched by this phase.
- No new third-party accounts or data contracts; every source named is
  keyless/public or already connected.
