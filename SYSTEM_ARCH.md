# SYSTEM_ARCH.md — Algo-Trade-Hub Master Architecture Reference

> **This is the single source of truth for this entire codebase.**
> Read this before touching any sub-system. Every rule here is enforced.

---

## Overview

Algo-Trade-Hub is a unified quantitative trading and sports analytics platform operating on a modern **Hybrid Architecture**:

1. **Frontend (Vercel)** — A React/Vite web application (`market_sentiment_tool`) serving as the unified "Kalshi Terminal" and "War Room" dashboard.
2. **Backend Compute (Custom VPS)** — Diverse Python engines (Quant, Weather, Macro, Sports) running autonomously separated from the frontend to optimize resources. Scheduled as hourly systemd timers on the VPS (see README, VPS deployment).
3. **Data Bridge (Supabase PostgreSQL)** — The central state layer bridging the Vercel UI and the VPS Daemons. 

---

## Directory Map

```
Algo-Trade-Hub/                          ← Root monorepo (one git repo)
│
├── tradehub/                     ← Canonical Python compute + operator package
│   ├── core/                             ← Core library modules & shared tools
│   │   ├── supabase_client.py           ← Unified Supabase write client (upsert_opportunities)
│   │   └── ...
│   ├── engines/                          ← Standalone specialized edge models
│   │   ├── weather_engine.py            ← NWS → Kalshi weather arbitrage
│   │   └── weather_maker.py             ← Weather market-making helper
│   ├── scripts/                          ← Operator scripts & daemons
│   │   └── scan.py                      ← Hourly scan (weather, gas, CPI, labor, sports), suggest-only
│   ├── api/                              ← FastAPI service (main.py, schemas.py, dependencies.py)
│   └── config/                           ← settings.yaml
│
├── tests/                                ← Root-level pytest suite
├── tools/                                ← Repo maintenance scripts (rewrite_imports.py, compare_junit.py)
├── models/                               ← Untracked runtime model artifacts (BTC/ETH .pkl, gitignored)
│
├── market_sentiment_tool/               ← Canonical backend/frontend service surface
│   ├── src/                             ← React app source
│   │   ├── pages/                       ← Dynamic Routing
│   │   │   ├── Index.tsx                ← 'War Room' (AI Swarm Activity Console)
│   │   │   ├── KalshiLab.tsx            ← 'Kalshi Lab' (Filters WEATHER, MACRO, CRYPTO)
│   │   │   └── SportsDesk.tsx           ← 'Sports Desk' (Filters SPORTS - EPL/F1/NBA)
│   │   ├── components/                  ← Reusable UI & strict ErrorBoundary wrappers
│   │   ├── hooks/                       ← Supabase useSupabaseData hooks
│   │   └── types/                       ← TypeScript interfaces matching Supabase schema
│   ├── package.json                     ← Node deps (React, Tailwind, Supabase JS)
│   └── .env                             ← FRONTEND CONFIG (VITE_ API URLs & Anon Keys)
│
├── shared/                              ← Shared cross-domain contracts and utilities
├── research/                            ← parked research, not imported by runtime (see research/README.md)
├── archive/                             ← Archived legacy docs, duplicate prompt packs, scratch material
│
├── SYSTEM_ARCH.md                       ← You are here
├── README.md                            ← Monorepo quick-start guide
└── .gitignore                           ← Root gitignore
```

---

## The Hybrid Hosting Model

The system separates concerns to heavily optimize the $5/mo VPS server limit while maintaining a highly responsive, high-volume data dashboard.

### 1. The VPS Backend (Data Generation & Orchestration)
The VPS focuses entirely on running heavy machine learning inference (LightGBM/FinBERT) and data scraping (NWS, FRED, Understat).

**Key Flow:**
1. The hourly `tradehub-scan` timer runs `python -m tradehub.scripts.scan` (weather + gas, suggest-only).
2. The scan runs the pure engines in `tradehub/engines/` (weather, gas, CPI, labor) and the sports consumers. The legacy daemon and its macro and quant engines were deleted. TSA/EIA engines now live as parked research under `research/engines` and are not run.
3. **Threshold-Free Discovery:** Engines ingest raw data and compute mathematical edges. Instead of filtering out low-edge markets, engines return *all* strictly tracked live markets (e.g., creating a massive grid of 100+ upcoming weather markets).
4. **Dynamic Data Tagging:** `scan.py` assigns a strict `edge_type` string to the payload: `'WEATHER'`, `'MACRO'`, `'CRYPTO'`, or `'SPORTS'`.
5. **Supabase Injection:** `supabase_client.py` uses the `SUPABASE_SERVICE_ROLE_KEY` to securely `UPSERT` normalized records into the `kalshi_edges` database table.

### 2. The Database Bridge (Supabase)
Supabase eliminates the need for a persistent Python API layer holding open local HTTP sockets between the VPS and the world. 

**Database Schema (`kalshi_edges`):**
- `id`: UUID
- `market_id`: Enforced unique identifier (e.g., `WEATHER_MIA_2026-03-23`)
- `title`: Human-readable event description 
- `edge_type`: Hardcoded category enum
- `our_prob`: Computed model percentage probability
- `market_prob`: Current retail bid/ask on the Kalshi exchange
- `edge_pct`: The spread between `our_prob` and `market_prob`
- `raw_payload`: Open JSONB wrapper storing context-specific properties (e.g., `forecast_temp`, `team_xg`, `cpi_actual`).

*Note:* Supabase Row Level Security (RLS) policies permit strictly read-only public access using the `SUPABASE_ANON_KEY`.

### 3. The Vercel Frontend (Data Consumption & UI)
Hosted on Vercel's global edge network, the React application renders the data.

**Dashboard Structure:**
By leveraging the `edge_type` tagged onto every database row, the frontend splits traffic cleanly into specialized views via `react-router-dom`:

- **The Kalshi Lab (`/kalshi-lab`):**
  Uses `useSupabaseData` to pull any row where `edge_type IN ('WEATHER', 'MACRO', 'CRYPTO')`. Features robust data tables allowing the user to scan the entire grid of upcoming markets, quickly identifying pricing inefficiencies dynamically.
- **The Sports Desk (`/sports`):**
  Pulls strictly `edge_type = 'SPORTS'`. Isolates heavier, sports-specific analytical UI components like the `SquadVisualizer`. The implementation forces strict `ErrorBoundary` wrappers to prevent fatal UI crashes if a single game's JSON payload is malformed.
- **The War Room (`/`):**
  Displays overarching paper-trading metrics, AI log streams, and portfolio performance.

---

## Environment Variable Architecture

Environment variables govern security isolation. The backend needs master-write access; the frontend ONLY gets read-access.

**`.env` (VPS Backend - Server Secret)**
```bash
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="eyJ..."        # MASTER KEY. Writes SQL.
FRED_API_KEY="..."                        # Data Sources
FOOTBALL_DATA_API_KEY="..."
```

**`market_sentiment_tool/.env` (Vercel Build - Public/Anon)**
```bash
VITE_SUPABASE_URL="https://your-project.supabase.co"
VITE_SUPABASE_ANON_KEY="eyJ..."           # READ ONLY KEY. Cannot modify tables.
VITE_API_BASE_URL="..."
```

---

## Integration Rules (Hard Rules — Never Break These)

1. **Frontend is read/display-only.** The React app in `market_sentiment_tool/` **never** executes proprietary business logic, model inference, or writes trading executions to the VPS.
2. **Tuple-Safe Python Extraction.** Ensure all ML feature engineering pipelines safely extract DataFrames. Unpacked model inputs (`df[0] if isinstance(df, tuple)`) are strictly required.
3. **Edge Types Must Map to UI.** Never inject a new data pipeline without strictly labeling the payload's `edge_type` string to match the React Frontend's filters.
4. **Brokerage keys never leave the local machine/VPS.** `APCA_API_SECRET_KEY` and similar tokens are strictly reserved for local/VPS environment files and never uploaded to Vercel or Supabase.

---

## Cleanup And Unification Notes

- `signal_events` is the canonical operator event store; `crypto_signal_events` is a compatibility view for crypto during migration.
- `shared/feature_engine.py` is the canonical feature-builder contract for active runtime builders.
- Archive legacy or duplicate material under `archive/` so graphify and vault indexing stay centered on canonical surfaces.

*Last updated: 2026-04-15 during cleanup and unification pass*

## Agent debate feed (phase-2 §3.2)

`tradehub/agents/` is a fenced side module: schema/store/importer/grader/payload for
TradingAgents debate artifacts, a subprocess runner (framework isolated in its own
venv; keys from env only), a CLI (`tradehub/scripts/agent_debate.py`), and two admin
read routes (`GET /api/agent-debates`, `.../{run_id}/report`) feeding the Workshop
page's Agent debates section. It imports no order/broker/portfolio code and nothing
in the order path imports it (test-enforced). Debate verdicts never feed model
probabilities, the scoreboard, or the trackers; grades (+5d/+20d direction hits,
Hold = no-call, flat = miss) live in `debate_record.json`, with a "No edge detected
in graded runs" banner at 30+ graded non-Hold +5d runs at <= 50% hits.

## Macro predictions dashboard (phase-3 §1)

`tradehub/macro.py` composes one card per macro engine (jobs, CPI, gas) from
reads the hub already makes -- jobs_scorecard rows, the scoreboard's
`current_runs`, and journal scores/forecasts/settlements -- behind
`GET /api/macro`, with each source guarded separately so a dead read degrades
only its own card's sections to null. The `/macro` page renders call, record
(paired Brier vs the market, gate/promotion, diagnostics flags as
annotations), and an 8-point trail; jobs trails are values, CPI/gas trails
are probabilities, and the payload's `trail_kind` keeps the two apart. `/jobs`
and `/cpi` remain the detail pages; the CPI card carries the display-only
honesty line the old nav label held.

## Workshop idea-builder parity (phase-3)

Three surfaces describe the Workshop contract and must not drift:
`tradehub/workshop/spec.py` MEASURES (what the engine runs), the editor's
MEASURES table in `src/lib/workshop.ts` (what can be clicked), and the
drafter's SYSTEM prose in `tradehub/workshop/draft.py` (what the drafting
model is told). `tests/test_draft_parity.py` walks all three plus the
condition/option-leg field vocabulary. Ticker lists in the editor are
`src/components/TickerListInput.tsx`: raw text is component state, the parse
flows to the spec on every keystroke, and the display never re-renders from
the parse (parse-on-change had made commas untypeable).

## Health heatmap (phase-3 §2)

`GET /api/health`'s report carries a `history` block: the last 14 CT days of
completed scanner runs, journal score days, per-forecaster freezes, and
diagnostics flag days, bucketed by `tradehub/health.py: build_history`
(pure). A cell is "silent" only for a gap inside an active stretch (both
neighbour days ran) -- window edges and quiet stretches are "none", no claim.
The Health page leads with the grid (family intensity = frozen count) and
demotes the timers/families lists into collapsed details; Problems stay
open. The orderbooks timer has no history source and is not drawn.

## Weather map (phase-3 §3.1)

`GET /api/weather/map` composes per-city summaries from journal forecasts
WITH payloads (station + ensemble mean live there; /api/weather strips
them): `tradehub/weather_map.py` groups the latest unsettled freeze batch
per (station, kind), lays ensemble/Kalshi/climatology probabilities per
bucket, and pairs the station's settled record against the market on the
same targets. The Weather page leads with an SVG US map
(`src/lib/usStates.ts` -- Census-derived state outlines projected once,
markers via the same projection), the selected city's card under it, and
the contract table demoted into a collapsed details section. The card
names the ensemble version behind its numbers.

## Weather ens-v2 (phase-3 §3.2, step 1)

`WeatherEnsembleV2` freezes beside ens-v1 in the journal (same forecaster
names, version "ens-v2"): ens-v1's member-share machinery with a fitted
per-station bias and kernel width replacing the fixed pre-results 2.0F
kernel. The fit is walk-forward on (ECMWF previous-runs day value, ACIS
actual) pairs -- `tradehub/data/hindcast.py`; GFS previous runs answer
nulls, so ECMWF is the fitting signal, stated in every payload
(`fit_source`) beside `fitted`, `bias`, `kernel_sigma`, `fit_pairs`.
Below 20 pairs a station freezes with ens-v1's exact parameters and
fitted=false. Rain keeps the plain member share in this step. Promotion
to the map page's headline numbers is grade-gated (200 settled per
family, Kevin's call), per the phase-3 spec.

## Weather ens-v2 step 2: model weighting + wider shelf

ens-v2 now reads its own pool (`MODELS_V2` = GEFS 0.25 + ECMWF IFS 0.25 +
ICON EPS, in `tradehub/data/ensemble.py`; ens-v1's pool is unchanged --
it is part of v1's frozen definition) and weights equally per model
family (`ensemble_prob_by_model`): each model's member-share first, then
the mean across models, so ECMWF's 51 members no longer outvote GEFS's
31 by headcount. GEM was probed and rejected (single control run, not an
ensemble). Payloads carry `weighting: equal_per_model` and
`members_by_model`.

## Weather ens-v2 step 3: the blend row

The registry adds `MarketShrunk` wrappers over the ens-v2 weather
forecasters only, so each family gains a `weather_*_cautious` scorecard at
version "ens-v2+w25": probability = market + 0.25 * (ens-v2 - market) --
the house's pre-registered shrink weight from `forecasters/shrunk.py`,
set once and never tuned on journal results. It freezes beside the raw
ens-v2 row as a pure function of it. ens-v1 gets no blend row; its record
stays the raw one the phase-3 measurements were taken on.

## Weather ens-v2 step 4: coverage expansion (and a correction)

STATIONS gains 19 high and 18 low series, each verified live 2026-11-01
(open markets for Nov 2, 2026; station read from the rules' (CLIxxx)
form -- Chicago temperatures settle at Midway, MDW, not O'Hare).
KXHIGHHOU had no open markets and was skipped. The map's station table
grows to match. CORRECTION to the phase-3 spec's rain plan: the
per-city KXRAIND* series are month-to-date precipitation accumulations,
not daily contracts, so the daily rain forecaster does NOT migrate to
them -- the KXRAIN umbrella stays. A daily per-city rain forecaster
would be a new design, not a migration.

## Sports dashboard (phase-3 §4)

`/sports` leads with a Predictions tab in the predictor estate's card
language: reviewer-passed picks as cards (model probability big,
model-vs-market meter, whole card linking to the sport's predictor site),
then unreviewed and flagged picks as cards -- flagged ones carry their
flag and are never featured. PL/NBA/F1 are estate link cards. The old
edges board is unchanged as the Grading desk tab; both tabs share one
fetch and the same board() reduction, so the two views cannot disagree.

## Crypto research desk (phase-3 §5)

`/crypto` is a research desk now; the ShadowBacktester is deleted and
`/shadow` redirects here. The page states plainly that the sniper worker
stopped 2026-06-02, keeps the OnChainPulse strip, and adds: (1) a tracked
Kalshi board (`tradehub/crypto_board.py`, GET /api/crypto/board) -- the
hourly ladder (KXBTCD/KXETHD) and 15-minute market (KXBTC15M/KXETH15M)
per coin beside Kraken spot, labelled market data. The ladder usually
quotes as a step (99c below spot, 1c above), so its line is reported as
the step bracket when no strike trades near 50. (2) The sniper's closed
record: `tradehub/scripts/sniper_regrade.py` graded the archive once
(2026-11-01) with the existing shadow evaluator -- 18,602 of 56,498
archived rows graded (67.1% dead zone), hit rate 54.8%, Brier 0.2513 --
into `tradehub/data/sniper_verdict.json`, served by
GET /api/crypto/sniper-verdict and never refreshed. Prices came from
Coinbase history: Kraken's OHLC is a rolling ~720-candle window and
cannot reach Apr-May 2026 (the script validates coverage and falls
back). (3) Research-item cards led by the venue lead-lag measurement,
the standing gate for any BTC daily-direction forecaster proposal.

## Reading comfort (phase-3 §6)

Workshop idea detail leads with a summary header (latest verdict +
headline, run count, lifecycle state from the idea's own timestamps);
the LifecyclePanel moves behind a "Lifecycle & live-paper gate" fold,
and older runs collapse to one line each (variation, verdict, date,
headline) with the latest run expanded. Portfolio's full position table
collapses behind its header (the composition summary above it already
says what we own; closed trades keep their own page). One timestamp
style and one money format now live in `src/lib/format.ts` (CT times
with suffix, `usd`) and are applied across the phase-3 pages (Macro,
Health, Weather, Sports, Crypto) and the Portfolio chart tooltip.
Journal settled-list grouping: SKIPPED BY DECISION -- the journal's
league table is already grouped by forecaster family by design, and
there is no separate flat settled list on the page to regroup; the
per-forecaster detail lives in JournalDetail.

## Drafter provider order: Gemini first (2026-11-01)

Kevin's call: the Anthropic key is not available to this project, so the
Workshop drafter's chain is now Gemini (free tier, GEMINI_API_KEY from AI
Studio; the envelope schema rides as the response JSON schema and is still
validated server-side) -> Claude where a key exists -> the OpenRouter free
list. A refusal from any provider still stops the chain. `unexpressed` is
now specified as a capability-request channel: each entry must name the
specific capability the engine would need added, what the words asked for,
and the closest stand-in drafted -- so a scoping gap arrives as a buildable
request. Activation: set GEMINI_API_KEY via scripts/set-vps-secret.sh and
forward it in the stack compose (beside ANTHROPIC_API_KEY).

## Weather map callouts + side-by-side (2026-11-01)

The five Northeast stations whose true positions collide at map scale
(BOS/NYC/EWR/TTN/PHL) draw their labeled circles fanned over the Atlantic
in latitude order (`MARKER_CALLOUTS` in src/lib/weatherMap.ts), each with
a dot and leader line at the true station point; DCA keeps its true
position. A layout test keeps every pair of labeled circles >=24px apart.
The city card's per-kind buckets are now a table with Ours and Kalshi in
their own columns (climatology muted) -- the side-by-side the map summary
always implied.

## Journal sports tab (2026-11-01)

The Journal gains a Sports tab: the /api/sports-record estate (the same
payload the Models page renders in full), one card per sport, headline
market first (moneyline, else the deepest record) with the remaining
markets under an "All markets" fold, and the NFL/CFB vs-Kalshi line from
the journal's own scores via the shared vsLine helper. A malformed
sports payload degrades to an unavailable note, never a crash.

## Oil forecaster (2026-11-01, on the weather/energy audit)

`oil_wti`@wti-v1 joins the journal on KXWTI (daily WTI, ICE settlement
~14:30 ET): the oil engine (tradehub/engines/oil.py) regresses the per-day
settlement change on the CL=F 5-close change, fit and applied at the same
decision time (close minus 2h), anchored on Kalshi's own settled values;
settlements skip weekends, so changes are per-day across their gap and the
horizon scales the same way. Beside it: kalshi_implied_oil, a persistence
baseline, and -- from day one, the row gas never got -- oil_wti_cautious
(w25 MarketShrunk, version-pinned). The Macro page gains an Oil card
beside Gas. Evidence for the build: KXWTI is open and liquid (Oct 30 event
traded 223,133 contracts) and Yahoo CL=F matched its settlement to the
cent, keyless; KXWTID/KXBRENT do not exist, KXOIL has no open markets.
Known v1 limitation, stated in tradehub/data/wti.py: CL=F is the
continuous series, so one close a month carries the contract roll.
The same change removes the Macro page's Gas card (the journal forecaster
keeps running and keeps its record): both audits graded gas a completed,
decisive loss, and a page that presents it as a live prediction is less
truthful than a tighter one. Oil takes the third slot.
