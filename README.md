# Algo Trade Hub

Kevin's paper-trading and research hub: a FastAPI backend and a React
frontend in one container, backed by a self-hosted Supabase on the same VPS.
Everything is paper or demo money — Alpaca paper books and a Kalshi demo
lane; there is no real-money order path.

## How it fits together

1. **The API** (`tradehub/api/`): `main.py` builds the FastAPI app — CORS,
   the lifespan (local `.env` load, cache warm-up), the two sports routes
   that still live there, and the frontend mount. Since step 20 the routes
   live in `tradehub/api/routers/` by area (workshop, portfolio, machine,
   journal, oil, valuation, screening, …), with the shared error taxonomy
   in `tradehub/api/shared.py`. The app serves the built SPA and the JSON
   API from the same origin; the browser never talks to the database
   directly.
2. **The database**: Supabase (Postgres + PostgREST + GoTrue), self-hosted
   in the `hubdb` compose stack on the VPS since 2026-11-14. The API and
   the runner scripts reach it server-side with the service role; row-level
   security is on, and the public surface is the API itself.
3. **The background work**: no daemon. Cron on the VPS runs the
   `tradehub/scripts/*_run.py` entry points — the journal forecasters
   freeze and settle predictions, the fifteen-minute runners score the
   live rule and its preregistered shadows, tape collectors keep the
   Kalshi/Binance tapes, and graders, screeners and watchers run on their
   own schedules. Each run is a short-lived process that reads and writes
   the database.
4. **The frontend** (`market_sentiment_tool/`): React + Vite. Pages are
   thin readers of the API: Journal, Oil (hourly and 15-minute Kalshi
   boards), Strategies, Workshop (idea backtests and the paper books),
   Portfolio, Guidance (valuation bands and fact sheets), Screening,
   Thesis Tracker, Weather (rain), Deals, and the Kalshi demo tab.

## Repository structure

```text
tradehub/                  # Python package: API, journal, models, runners
tradehub/api/routers/      # the API routes, split by area (step 20)
market_sentiment_tool/     # React frontend + Supabase migrations
market_sentiment_tool/supabase/migrations/  # schema history (see
                           # docs/superpowers/plans/migrations-applied.md
                           # for what has actually been applied)
docs/                      # plans, preregistrations, the review backlog
research/                  # parked research, not imported by runtime
```

## Quick start

Backend (from the repo root):

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r pyproject.toml --extra dev --extra scanner
.venv/bin/python -m pytest            # the full suite is the gate
.venv/bin/python -m uvicorn tradehub.api.main:app --port 8000
```

Frontend:

```bash
cd market_sentiment_tool
npm install
npm run dev        # Vite dev server; npm run build for the production bundle
npm run typecheck  # the type gate (plain tsc at the root checks nothing)
```

## Environment

Secrets live in `.env` files and in the VPS stack's environment — never in
git. The API needs the Supabase URL and service-role key, plus provider
keys for the data sources a runner uses (Kalshi, Alpaca paper, FRED, …).
SEC EDGAR access requires `SEC_CONTACT_EMAIL` to be set; the code refuses
to call EDGAR without it. The frontend needs no secrets: it reads
everything from the API.

## VPS deployment

Every push to `main` runs `.github/workflows/deploy-tradehub.yml`: the
test suites, a build of `ghcr.io/kevinsigey/tradehub`, then
`deploy tradehub <sha>` on the VPS compose stack (`/opt/stack`),
health-checked at `/api/health`. Verify a deploy by the workflow run for
the merge commit and the `TRADEHUB_TAG` the stack reports — a merged PR
is not a deployed PR. The background jobs run under systemd timers
(`tradehub-scan.timer` hourly, `tradehub-settle.timer`) and the deploy
user's crontab (the fifteen-minute runners, tape collectors and graders).

## Agent debates

On-demand LLM debate memos live in `tradehub/agents/` (spec:
`docs/TradingAgents-Ideas-Feed-Spec.md`). One ticker per run, triggered by
`python -m tradehub.scripts.agent_debate run <TICKER>`; the framework runs
in its own venv (`tradehub/agents/requirements.txt`, or
`TRADEHUB_AGENTS_PYTHON`), never inside the hub process, and has no path
to orders. Runs are stored as artifacts (failures included), shown on the
Guidance page under "Agent debates" with the standing label that it is
not a model, and graded at +5/+20 trading days into a record kept
separate from every model statistic. Set `TRADEHUB_AGENTS_DIR` to a
persistent volume in production so artifacts survive deploys.
