"""
FastAPI Main — Thin API layer over the Kalshi Edge System.

Does ZERO business logic — only queries Supabase or the in-memory
scanner cache and returns typed JSON. All heavy lifting stays in
the scan scripts and engine modules.

Run locally:
    uvicorn api.main:app --reload --port 8000

Then visit: http://localhost:8000/docs  (Swagger UI — auto-generated)
"""

import functools
import logging
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import pandas as pd
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from tradehub.core.env import load_local_env
from tradehub import snapshots as _snapshots
from tradehub.health import collect_health, public_health_report
from tradehub.api.schemas import (
    HealthResponse, Position, PnLSummary,
    ShadowPerformanceResponse,
)
from tradehub.api.dependencies import get_supabase
from tradehub.api import admin
from tradehub.api.frontend import mount_frontend
from tradehub.api.swr import SwrCache
from tradehub.workshop import store as workshop_store
from tradehub.workshop.data import UnknownSymbol, bars as workshop_bars, closes as workshop_closes, \
    analyst as workshop_analyst, earnings_dates as workshop_earnings, fred_series as workshop_fred, \
    div_yields as workshop_div_yields, release_dates as workshop_release_dates, rule_series, \
    ticker_info as workshop_ticker_info, \
    with_rule_bars
from tradehub.workshop.draft import DraftUnavailable, draft_spec
from tradehub.workshop.events import RELEASES, EventSpec, run_event_test
from tradehub.workshop.fomc_calendar import statement_times as workshop_fomc_times
from tradehub.workshop.playbook import draft as playbook_draft, dropped_tickers as playbook_dropped
from tradehub.workshop.engine import analysis as workshop_analysis, daily_frame as workshop_daily_frame, gate_check, \
    run_test, target_and_reason, tickers_for
from tradehub.portfolio.autotrade import option_structure_problems
from tradehub.portfolio.sectors import idea_sector
from tradehub.workshop.playcheck import play_check as _play_check_math
from tradehub.workshop.data import NY
from tradehub.workshop.record import shadow_summary
from tradehub.workshop.spec import IdeaSpec, blank_spec
from tradehub.engine_catalogue import engine_catalogue
from tradehub.engine_health import engine_health
from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses, table_missing
from tradehub.journal.legacy import journal_scores, merge_track_record
from tradehub.journal.scoring import headline as journal_headline
from tradehub.journal.standings import standings as journal_standings
from tradehub.journal.standings import verdict_sentence as journal_verdict_sentence
from tradehub.quarantine import QUARANTINE_MARK, QUARANTINE_NOTE, quarantine_report
from tradehub.scoreboard import current_runs, market_comparison
from tradehub.scripts.shadow_performance import MissingCredentialError, build_shadow_timeline_response

log = logging.getLogger(__name__)

from tradehub.api.shared import (
    TABLE_MIGRATIONS, SNAPSHOT_MAX_AGE_SECONDS, _snapshot,
    _is_missing_table, _missing_table_message, _table_fault,
    _is_missing_credential, _credential_variables, _credential_service,
    _missing_credential_message,
    _STATUS_MISSING_TABLE, _STATUS_MISSING_CREDENTIALS, _STATUS_INTERNAL_ERROR,
    _CODE_MISSING_TABLE, _CODE_MISSING_CREDENTIALS, _CODE_INTERNAL_ERROR,
    _fetch_all, POSTGREST_CAP,
)


def _warm_swr_caches() -> None:
    """Build the SWR-cached payloads once at boot, so a container restart
    doesn't hand the first visitor a 10s wait (Nov 12: the post-deploy
    restart left every cache cold at once and pages hung). Fail-soft: a
    failed warm-up leaves the caches cold and the endpoints behave
    exactly as they did before this cache existed."""
    try:
        supabase = get_supabase()
        if supabase is None:
            return
        _FIFTEEN_RULE_CACHE.get(lambda: _fifteen_rule_payload(supabase, strict=True),
                                client=supabase)
        from tradehub.gaps.report import desk

        _GAP_DESK_CACHE.get(lambda: desk(supabase, datetime.now(timezone.utc)),
                            client=supabase)
    except Exception:  # noqa: BLE001
        log.exception("api: cache warm-up failed")


# ── App ─────────────────────────────────────────────────────────────────────
# The developer-local `.env` is loaded here, in the app's lifespan, and NOT at
# import time. That placement is the whole point: a lifespan handler runs when
# uvicorn actually boots the server, so `import tradehub.api.main` -- which the
# test suite does, several times -- leaves `os.environ` alone. See
# `tradehub.core.env` for why that matters. In production this is a no-op:
# the container gets real variables from compose and ships no `.env`.
@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_local_env()
    threading.Thread(target=_warm_swr_caches, daemon=True).start()
    yield


app = FastAPI(
    title="Algo Trade Hub API",
    description="Thin API layer over the Kalshi prediction engine. Paper trading only until 200+ trade +EV proof.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow Vite (localhost:5173) and any future React frontend
import yaml
_settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
try:
    with open(_settings_path) as f:
        _cfg = yaml.safe_load(f)
    _cors_origins = _cfg.get("api", {}).get("cors_origins", ["*"])
except Exception:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    """Set on every response, the built site included. The CSP only covers framing and base/object
    tags, so it can't break the page's scripts or its calls to Supabase."""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    return response


# ── War Room SPA (mounted last so every /api route above wins) ─────────────
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "market_sentiment_tool" / "dist")))



# ── Routers (step 20: main.py split by area) ────────────────────────────────
from tradehub.api.routers import (  # noqa: E402
    crypto, deals, desks, ideas, journal, machine, oil, portfolio, screening,
    system, thesis, valuation, weather, workshop,
)

for _r in (system.router, portfolio.router, workshop.router, ideas.router,
           deals.router, oil.router, desks.router, machine.router, thesis.router,
           journal.router, crypto.router, weather.router, screening.router,
           valuation.router):
    app.include_router(_r)

# Names tests and other modules historically import from main; the handlers
# moved, so main re-exports them from their routers.
from tradehub.api.routers.workshop import _fred_start, _latest_saved_map, _play_check  # noqa: E402,F401
from tradehub.api.routers.ideas import _IDEAS_CACHE, _IDEAS_REBUILD, _build_ideas, _bust_ideas_cache, _today  # noqa: E402,F401
from tradehub.api.routers.oil import _FIFTEEN_RULE_CACHE, _fifteen_rule_payload, oil_fifteen_rule  # noqa: E402,F401
from tradehub.api.routers.desks import _GAP_DESK_CACHE  # noqa: E402,F401
from tradehub.api.routers.journal import get_scoreboard, get_shadow_performance  # noqa: E402,F401
from tradehub.api.routers.ideas import _ideas_fingerprint, _rebuild_ideas_in_background  # noqa: E402,F401
from tradehub.api.routers.desks import get_gap_desk  # noqa: E402,F401
from tradehub.api.routers.portfolio import get_kalshi_demo, get_pnl_summary, get_positions  # noqa: E402,F401
from tradehub.api.routers.workshop import _DEBATE_IN_FLIGHT  # noqa: E402,F401

mount_frontend(app, FRONTEND_DIST)


# ── Dev entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "tradehub.api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
    )
