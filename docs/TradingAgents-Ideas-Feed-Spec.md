# TradingAgents as an Ideas Feed — Integration Spec

**Date:** 2026-10-31 · **Status:** Spec for build · **Decision:** Kevin, 2026-10-31 — "Spec it into the hub as an Ideas feed" (chosen over a standalone trial after reviewing the @laeshaai reel on Tauric Research's TradingAgents).

**One-line summary:** Add the open-source TradingAgents multi-agent LLM framework to the algo trade hub as a third source in the Trading HQ **Ideas record** — on-demand, per-ticker debate memos with a risk-reviewed verdict — kept strictly separate from the hub's model signals, trackers, and order paths, and graded after the fact against real price action.

---

## 1. What the framework is (source facts)

- **TradingAgents** (TauricResearch/TradingAgents, open source, GitHub): a LangGraph-based multi-agent LLM framework that simulates a trading firm for a single ticker:
  - **Analyst team:** fundamentals, sentiment, news, technicals — each produces a report from pulled data.
  - **Researcher team:** a bull and a bear agent debate over the analyst reports.
  - **Trader agent:** issues a decision from the debate.
  - **Risk team:** risk analysts review the decision before it is finalized.
  - Output: a structured decision (Buy / Overweight / Hold / Underweight / Sell in current versions) plus a full markdown decision report.
- The reel that prompted this (Oct 24, 2026) showed a $100 account at $157 after a few days. That is a demo, not evidence: no drawdown, no win rate, no sample size. **Nothing from the reel is a design input.** The framework's value here is the structured debate artifact, not a proven edge.
- At build time, pin the framework to a specific commit SHA and record it. Framework output formats drift between versions; the importer must tolerate that (see §5).

## 2. Goals and non-goals

**Goals**
1. One new Ideas source type, `agent_debate`, alongside the existing manual ideas and model-derived entries in the Trading HQ Ideas record.
2. Every run produces a durable, dated artifact (JSON metadata + full markdown report) that the Ideas feed renders as a labeled card.
3. A grading loop that scores past verdicts against real subsequent price action, reported separately as the "agent debate record."
4. Zero contact with execution: no orders, no position sizing, no changes to the paper book.

**Non-goals**
- Not a signal. Debate verdicts never feed model probabilities, the scoreboard, the FanDuel/model trackers, or the Strategy HQ tracker.
- Not a scanner. No universe runs, no scheduler-driven runs in v1. One ticker per run, manually triggered.
- Not a replacement for Kevin's files. His pattern factor and model outputs remain the primary research record; a debate memo is an annotation beside them.
- No live trading, ever, in this module. (The framework advertises broker execution upstream; that code path is not imported.)

## 3. Where it lands in the hub

- **Trading HQ → Ideas record:** new entry source `agent_debate`. Cards render in the same feed as other ideas, visually distinct (see §6).
- **New package:** `tradehub/agents/` — runner, artifact store, importer, grader — a sibling of `tradehub/strategy/`. It must not import from Trading HQ order code, and order code must not import from it (test-enforced, §8).
- **Data dir:** `tradehub/agents/data/runs/` — one folder per run: `run.json` + `report.md`. Snapshotted inputs note (see §5) lives in `run.json`.
- **Operator CLI:** `tradehub/scripts/agent_debate.py` with `run <TICKER> [--date YYYY-MM-DD]`, `import`, and `grade` subcommands, mirroring the `strategy_tracker.py` pattern (writes a JSON payload + optional HTML preview for the frontend).

## 4. Run model

- **Trigger:** manual only in v1 (CLI; an Ideas-page "Run debate" button is a frontend follow-up, not v1 scope).
- **Inputs:** ticker (required); as-of date (optional, default = latest completed session). Historical as-of runs use the framework's backtest mode against that date's data — allowed, but the artifact must record that the run is historical, not live.
- **Caps (config, defaults):** max 10 runs/day; per-run LLM spend ceiling recorded and enforced where the provider reports it; a run that exceeds its ceiling stops and is stored as `status: failed_cost` with whatever partial output exists.
- **Keys:** LLM provider keys via environment only, never in the repo or artifacts. The provider/model used is recorded per run (it changes output materially).
- **Failure handling:** a failed or partial run is stored and rendered as failed/partial with its error class. Never silently dropped, never retried in a loop.

## 5. Run artifact schema (`run.json`)

Required fields:

| Field | Notes |
|---|---|
| `run_id` | UUID or timestamped slug |
| `ticker` | As requested, uppercased |
| `run_at_ct`, `run_at_utc` | Wall-clock run time, both zones |
| `as_of_date` | The market date the debate is about |
| `historical` | `true` when `as_of_date` is not the latest session |
| `framework_version` | TradingAgents git SHA (pinned at build) |
| `llm_provider`, `llm_model` | Exact model string |
| `decision` | Framework's final rating, verbatim (e.g. `Buy`, `Hold`) |
| `analyst_summaries` | fundamentals / sentiment / news / technicals, short text each |
| `bull_case`, `bear_case` | Short text, from the researcher debate |
| `trader_rationale` | Short text |
| `risk_verdict` | Short text, from the risk team |
| `report_path` | Relative path to `report.md` (full framework output) |
| `inputs_note` | Which data sources the run actually pulled (news/social/fundamentals/technicals), as reported by the framework |
| `cost_usd` | Provider-reported spend, or `null` → rendered "not recorded" |
| `status` | `complete` / `partial` / `failed_cost` / `failed_error` |

Rules:
- Any field the framework does not produce is `null` and renders as **"not recorded"** — never backfilled, never estimated, never 0.
- Claims inside the report text (price targets, statistics the agents cite) stay inside the report. They are never promoted into hub data fields, cards, or scoreboards.

## 6. Display (Ideas feed card)

Mandatory labels on every card, per Kevin's standing labeling rule (state, date, as-of, current-or-stale):

- Header chip: **"LLM agent debate — not a model signal"** (exact wording).
- Ticker, decision chip (framework's rating verbatim), run date and time CT, as-of date.
- Framework version (short SHA) and LLM model string.
- **Stale flag:** a run is stale after 5 trading days from its as-of date; stale cards render with the stale label, they do not disappear.
- Historical runs carry a **"historical run"** label next to the as-of date.
- Expandable: analyst summaries, bull case, bear case, trader rationale, risk verdict, and a link to the full report.
- The card never shows a price target, return figure, or probability as a hub-endorsed number. If the summary text contains one, it is visibly inside the quoted debate text, not in card metadata.

## 7. Grading loop

- The `grade` subcommand (also run inside the existing refresh workflow) grades each completed run at fixed horizons: **+5 trading days** and **+20 trading days** after `as_of_date`, using the hub's existing price artifacts (no new price vendor).
- Grade = direction hit: Buy/Overweight counts as long, Underweight/Sell as short, **Hold = no-call** (excluded from the hit rate, counted separately). Hit if the sign of the ticker's return over the horizon matches the call's direction; a flat return (exactly 0.0%) is a miss, recorded as such.
- Results append to `tradehub/agents/data/debate_record.json`: per run, per horizon — return %, hit/miss/no-call. Ungraded horizons render as "pending," never as 0.
- The feed header shows the agent debate record separately: graded n, hit rate at each horizon, no-calls excluded and counted. It is never averaged into any model statistic anywhere in the hub.
- **Falsification rule:** after 30 graded non-Hold runs at the +5d horizon, if the hit rate is ≤ 50%, the feed header carries a standing **"No edge detected in graded runs"** banner. The banner is informational; removing the module stays Kevin's call.

## 8. Guardrails and tests

Guardrails:
- The agents package runs the framework in its own environment; API keys come from env vars only.
- No import path from `tradehub/agents/` to any broker, order, or portfolio-mutation code — and none back.
- Runs are read-only with respect to the book, the trackers, and Trading HQ state. The only writes are new run artifacts and appended grades.
- Daily run cap and per-run cost ceiling are config, with the defaults in §4.

Tests (pinned, in `tests/test_agent_debate.py`):
1. Schema validation: a fixture `run.json` missing optional fields imports cleanly and renders "not recorded" for them.
2. Label test: the rendered card payload contains the exact "not a model signal" chip text, run timestamp, and stale flag logic (a 6-trading-day-old fixture run renders stale).
3. No-execution test: importing the agents package does not import any order/broker module (assert on `sys.modules`).
4. Grading math: fixture prices produce the expected hit/miss/no-call at both horizons, including the flat-return-is-a-miss case.
5. Hold handling: a Hold fixture run is excluded from the hit rate and counted as a no-call.

## 9. Acceptance criteria

- `agent_debate.py run PLTR` (or any liquid ticker) produces a complete run artifact that imports into the Ideas payload with all §6 labels present.
- A deliberately failed run (bad ticker) is stored and rendered as failed, not dropped.
- `grade` on fixture data reproduces the §7 math exactly; the debate record displays separately from model stats.
- The full existing test suite passes in the project's uv environment (the bare-environment dependency failures seen on Oct 30 are pre-existing and out of scope).
- README and SYSTEM_ARCH describe the module accurately: an on-demand LLM debate feed for the Ideas record, qualitative, graded after the fact, no execution path.

## 10. Open questions for Kevin

1. **LLM provider/model:** the framework supports several. Cost per full debate varies a lot by model; a mid-tier model keeps a 10-run day cheap, a frontier model reads better. Default if unanswered: mid-tier, recorded per run so results stay comparable only within a model.
2. **Backtest-mode runs in v1?** The schema supports historical as-of runs; enabling them in v1 costs little but doubles the grading surface. Recommendation: v1 live-date runs only, historical in v2.
3. **First tickers:** natural first batch is the names already in his research files (the Nov 2–6 earnings slate), so debate verdicts can be compared against his pattern factor after the prints.
