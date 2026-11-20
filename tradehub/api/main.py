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
from tradehub.sports.scan import edge_row, edge_sigma_score
from tradehub.sports.scorecard import reviewer_scorecard

log = logging.getLogger(__name__)

from tradehub.api.shared import (
    TABLE_MIGRATIONS, SNAPSHOT_MAX_AGE_SECONDS, _snapshot,
    _is_missing_table, _missing_table_message, _table_fault,
    _is_missing_credential, _credential_variables, _credential_service,
    _missing_credential_message,
    _STATUS_MISSING_TABLE, _STATUS_MISSING_CREDENTIALS, _STATUS_INTERNAL_ERROR,
    _CODE_MISSING_TABLE, _CODE_MISSING_CREDENTIALS, _CODE_INTERNAL_ERROR,
    _TIER_ORDER, _fetch_all, POSTGREST_CAP,
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


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1: /api/health
# ════════════════════════════════════════════════════════════════════════════
SPORTS_PAGE_DEFAULT = 100

_SPORTS_ENGINES = {"nfl": "sports_nfl", "cfb": "sports_cfb"}



def _page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > SPORTS_PAGE_MAX or offset < 0:
        raise HTTPException(status_code=422, detail=f"limit must be 1..{SPORTS_PAGE_MAX} and offset >= 0")
    return limit, offset

SPORTS_REVIEW_SCAN = 5000



def _is_upcoming(row: dict, now: datetime) -> bool:
    """A row with no parsable start_utc is not upcoming and is never shown."""
    start = (row.get("raw_payload") or {}).get("start_utc")
    if not start:
        return False
    try:
        return datetime.fromisoformat(start) > now
    except (TypeError, ValueError):
        return False



def _tier_of(row: dict) -> str | None:
    return ((row.get("raw_payload") or {}).get("tier"))



def _sports_rank(row: dict) -> tuple[int, int, float]:
    """Sort key: top_pick, then any other candidate, then the rest; then the confidence score.

    A `filtered` row is one the candidate filter rejected, so it ranks below every candidate
    regardless of its edge — a large gap the filter already refused should not lead the board. That
    grouping is the outer key and the confidence score only ever orders rows WITHIN it.

    Within a tier, the sort is on `edge_sigma_score` when the feed published a sigma, because two
    equal edges at different confidences are not equal claims. The score is capped, floored and
    `None` when there is no sigma, and the fallback is the raw edge: NOT 0.0, which would sort the
    row last in its tier and read as "the least interesting pick here" — a claim, made by a
    fallback, about a row whose confidence is merely unknown.

    The stored column is `edge_pct` (this runs before `edge_row`); the same number is published to
    clients as `rank_edge_pct`, which is why the fallback is that number.
    """
    tier = _tier_of(row)
    if tier == "top_pick":
        group = 0
    elif (row.get("raw_payload") or {}).get("candidate"):
        group = 1
    else:
        group = 2
    score = edge_sigma_score(row.get("edge_pct"), (row.get("raw_payload") or {}).get("sigma"))
    if score is None:
        # A partly-publishing feed compares INCOMMENSURABLE UNITS in this one key, deliberately, and
        # the ordering it produces can INVERT the board -- not merely bias it toward the scored rows
        # at equal edge, which is how this used to be described and which undersells it. A scored
        # row's key is a z-score; an unscored row's is its edge in decimal. So the comparison is
        # score-vs-edge, not score-vs-score, and those are not two numbers on one scale: a scored
        # 2pp edge at sigma 0.001 scores 20.0 and outranks an unscored 40pp edge outright, and the
        # row that leads its tier is the one the 20.0 cap invented. The cap is the tell -- a
        # saturated score is a value the feature refused to measure precisely, and here it is
        # out-measuring a real 40pp disagreement.
        #
        # Every one of those terms is reachable: `sigma_floor` is 0.005, and a predictor publishing
        # a width of 0.1pp on a genuine edge produces exactly 20.0. So this is a latent inversion
        # that fires on the first run where one sport publishes a sigma and another row does not --
        # which is the same run on which the page's sentence starts claiming a confidence ranking.
        #
        # The alternative is inventing a sigma for the row that has none, which is the one thing
        # this feature must never do -- a made-up sigma ranks confidently off nothing, and
        # 0.10 / 0.005 is the cap. So the bias stands, it is recorded here rather than left to be
        # discovered, and the page's sentence says it out loud ("...wherever the feed publishes one,
        # and by raw edge for the rest"), because a reader comparing a 4pp z-scored row against a
        # 4pp unscored one is owed the reason one of them led. The disclosed sentence is what makes
        # this acceptable rather than a defect: the page does not claim a total order it cannot
        # deliver, it names the fallback and the fact that the two are not on one scale.
        score = float(row.get("edge_pct") or 0)
    return group, _TIER_ORDER.get(tier, 9), -score



def _ranking_mode(rows: list[dict]) -> str:
    """Which ranking the response actually used, so the page can say so.

    Reads the STORED row, not the served one, and that is not incidental: `sports.scan._edge_row` is
    what writes `raw_payload["sigma"]` at all, and `edge_row` deliberately withholds sigma from the
    payload the page receives. So this is the only place the number exists, and it is also the only
    place the ranking can honestly be described from.

    Reporting the mode rather than implying sigma always applies is the whole point: a page that
    claims to rank by confidence while ranking by raw edge is worse than one that never claimed it.

    `edge_sigma` means the score was in play for at least one row — which is exactly the condition
    under which the sort stopped being a pure raw-edge sort. A *published* sigma of zero counts,
    because it was floored and scored like any other value and the sort did use it; a page reporting
    `raw_edge` there would be describing a sort that did not happen. A *negative* sigma does not
    count, because the score is `None` for it: a corrupt value is handled exactly as an absent one
    is, so it is never the thing that put a row on the board, and a page must not claim the sort used
    confidence because one broken predictor published a negative width. An empty set reports
    `raw_edge`: nothing was ranked, so the answer that claims the least is the honest one.
    """
    for row in rows:
        if edge_sigma_score(row.get("edge_pct"), (row.get("raw_payload") or {}).get("sigma")) is not None:
            return "edge_sigma"
    return "raw_edge"

SPORTS_PAGE_MAX = 200


@app.get("/api/sports-record", tags=["Sports"])
def get_sports_record() -> dict[str, Any]:
    """Each sports predictor's own published record, normalised. Display only: nothing here is scored.

    Synchronous on purpose, like `/api/health`: `collect` fetches the five sites in parallel with a 6 s
    timeout and a five-minute cache, and one sport being down only marks that sport `unavailable`.
    """
    from tradehub.sports_record import collect

    return collect()


@app.get("/api/sports-edges", tags=["Sports"])
def get_sports_edges(
    sport: str | None = None,
    tier: str | None = None,
    limit: int = SPORTS_PAGE_DEFAULT,
    offset: int = 0,
    supabase=Depends(get_supabase),
):
    """Upcoming SPORTS edges (Top Picks first) plus the reviewer keep-or-drop scorecard.

    Three things matter here and each has bitten before:

    1. Every read pages with an ORDERED `.range()`. PostgREST caps a response at 1000 rows, so a
       single `.execute()` silently truncates and `total` would be a lie on a larger table — and
       without `.order()` the pages are not guaranteed to line up at all.
    2. Ranking is applied to ALL matching rows BEFORE offset/limit. Sorting after slicing ranks
       each arbitrary offset window on its own, so a `top_pick` can be stranded on a later page
       behind `filtered` rows.
    3. `tier` lives inside raw_payload and cannot be filtered by the database, so that one
       filter is applied in Python — but the upcoming/started test IS pushed into the query via
       `expires_at`, and Python re-checks it because a malformed `start_utc` must never show.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    if sport is not None and sport not in _SPORTS_ENGINES:
        raise HTTPException(status_code=422, detail=f"sport must be one of {sorted(_SPORTS_ENGINES)}")
    if tier is not None and tier not in _TIER_ORDER:
        raise HTTPException(status_code=422, detail=f"tier must be one of {sorted(_TIER_ORDER)}")
    limit, offset = _page(limit, offset)

    now = datetime.now(timezone.utc)

    def build(q):
        q = q.select("*").eq("edge_type", "SPORTS")
        if sport is not None:
            q = q.eq("engine", _SPORTS_ENGINES[sport])
        # Not-started is the cheap, indexable half of "upcoming"; start_utc inside raw_payload
        # is checked again below because it is what the reviewer/scan actually wrote.
        return q.gte("expires_at", now.isoformat())

    candidates = [r for r in _fetch_all(supabase, "kalshi_edges", build) if _is_upcoming(r, now)]
    if tier is not None:
        candidates = [r for r in candidates if _tier_of(r) == tier]

    # Rank globally, THEN page. top_pick first, then any remaining candidate, then the rest;
    # within a tier by edge_pct descending. Ranking after the slice would let each offset window
    # order itself, stranding a top_pick behind filtered rows on a later page.
    candidates.sort(key=_sports_rank)
    total = len(candidates)
    rows = candidates[offset:offset + limit]
    # Counted over the whole filtered set, before slicing. The UI needs this because a page of
    # rejects is not evidence that nothing passed: rows are ranked candidates-first, so page 2+ is
    # always the reject tail, and a page-derived count reports "all rejected" on a board that has
    # picks on page 1.
    candidate_count = sum(1 for r in candidates if _tier_of(r) != "filtered")

    # sports.scan.edge_row owns the row shape AND the honesty rules: edge_pct is the after-fee
    # edge vs the entry price (not vs market_prob, the mid), it is withheld from any row the
    # candidate filter rejected, quote_spread travels so a wide quote is visible, and a placeholder
    # engine_version is blanked rather than printed as the word "unknown".
    edges = [edge_row(row) for row in rows]

    reviews = _fetch_all(supabase, "sports_reviews",
                         lambda q: q.select("*").eq("status", "ok"), cap=SPORTS_REVIEW_SCAN)
    settled = _fetch_all(supabase, "predictions",
                         lambda q: q.select("market_ticker,result")
                         .in_("engine", sorted(_SPORTS_ENGINES.values())).eq("status", "SETTLED"),
                         cap=SPORTS_REVIEW_SCAN)
    results = {r["market_ticker"]: r["result"] for r in settled}
    return {
        "as_of": now.isoformat(), "edges": edges, "total": total, "limit": limit, "offset": offset,
        # Whole-set candidate count. A client cannot derive it from one page, and deriving it is
        # what made the "everything was rejected" banner wrong on every page after the first.
        "candidate_count": candidate_count,
        # Which ranking produced the order above, over the WHOLE filtered set rather than this page:
        # a sigma on page 3 is a sigma the sort used, and a page-local count would report `raw_edge`
        # while rows were being scored. The page states it, because claiming a confidence ranking it
        # is not applying is worse than never claiming one.
        "ranking": _ranking_mode(candidates),
        "reviewer_scorecard": reviewer_scorecard(reviews, results),
    }


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
