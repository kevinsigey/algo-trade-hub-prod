"""Gap tracker, quarantine, macro and jobs desks routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from tradehub.api.dependencies import get_supabase
from tradehub.api.swr import SwrCache
from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses
from tradehub.quarantine import QUARANTINE_MARK, QUARANTINE_NOTE, quarantine_report


from tradehub.api.shared import (
    TABLE_MIGRATIONS, _snapshot,
    _table_fault,
)
from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

log = logging.getLogger(__name__)

from tradehub.api.routers.weather import _macro_live
router = APIRouter()


# The desk build takes ~5s and intermittently hit the Postgres statement
# timeout under load, which the old dict cache turned into a visitor-facing
# 500 (a failed build cached nothing). Stale-while-revalidate instead: once
# any build has succeeded, visitors always get that payload; rebuilds happen
# in the background and their failures never reach the page. A cold failure
# (no payload ever built) still raises the table fault, as before.
_GAP_DESK_CACHE = SwrCache(120)


@router.get("/api/gaps/desk", tags=["Gap tracker"])
def get_gap_desk(supabase=Depends(get_supabase)):
    """The Kalshi gap tracker's paper ledger and evidence. Research only: nothing here places an order."""
    from tradehub.gaps.report import desk

    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        return _api._GAP_DESK_CACHE.get(lambda: desk(supabase, datetime.now(timezone.utc)),
                                   client=supabase)
    except Exception as exc:  # noqa: BLE001
        raise _table_fault("gap_snapshots", exc) from exc


def _target_day(target: str):
    """The operating day of a Kalshi journal target: 'kalshi:KXHIGHNY-26OCT16-T75' -> 2026-10-16.

    The date is the SECOND dash-separated part of the ticker (`%y%b%d`); the last part is the strike or
    city. Parsed to a real date so days compare chronologically across months (as text, '26OCT' sorts
    after '26NOV').
    """
    parts = target.removeprefix("kalshi:").split("-")
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError:
        return None


@router.get("/api/macro", tags=["Macro"])
def get_macro(supabase=Depends(get_supabase)):
    """The Macro predictions dashboard (phase-3 §1): one card per macro engine,
    composed from reads the hub already makes (jobs scorecard, scoreboard
    current runs, journal scores/forecasts/settlements). Composition, not a
    verdict: every read is guarded separately, so one dead source degrades its
    own card's sections to null -- the page renders those as "unavailable" --
    instead of taking the dashboard down or, worse, filling the gap with a
    plausible zero.

    Served from the hourly snapshot while fresh (step 5); the live build
    below is the fallback."""
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    snap = _snapshot("macro")
    if snap is not None:
        return snap["payload"]
    return _macro_live(supabase)


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/jobs-scorecard (service-role read, like /api/track-record;
# jobs_scorecard keeps owner-only RLS)
#
# Registered BEFORE mount_frontend below: the SPA is mounted at "/", so a route
# added after it is shadowed and this endpoint would answer with the app shell.
#
# No limit: the table holds one row per (series, reference_month), so it is two
# rows per month of history rather than a growing event log.
# ════════════════════════════════════════════════════════════════════════════
# The scorecard's series -> the engine whose gate applies. `unemployment` is deliberately absent:
# its u3-naive-v0 baseline is not a gated engine.
SCORECARD_ENGINE = {"payrolls": "labor_nowcast"}


@router.get("/api/jobs-scorecard", tags=["Jobs Scorecard"])
async def get_jobs_scorecard(
    series: str = Query("payrolls", pattern="^(payrolls|unemployment)$"),
    supabase=Depends(get_supabase),
):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    result = (
        supabase.table("jobs_scorecard").select("*").eq("series", series).order("reference_month").execute()
    )
    rows = result.data or []
    if not rows:
        return rows
    # Kevin's decision: the /jobs page shows the engine's gate status next to the nowcast. The
    # scorecard is built out of band, so the status is not on the row and has to be looked up --
    # per (engine, engine_version), defaulting to SHADOW. The unemployment panel is a naive
    # baseline rather than a gated engine, so it must not borrow labor_nowcast's promotion.
    engine = SCORECARD_ENGINE.get(series)
    versions = {row.get("engine_version") for row in rows if row.get("engine_version")}
    statuses: dict[tuple[str, str], str] = {}
    if engine and versions:
        try:
            statuses = latest_gate_statuses(supabase, {(engine, version) for version in versions})
        except Exception:
            # Failing closed: no gate record means SHADOW, and a lookup error must not take the
            # whole page down when the rows themselves are readable.
            log.exception("api: jobs scorecard gate-status lookup failed")
            statuses = {}
    for row in rows:
        version = row.get("engine_version")
        row["engine"] = engine
        row["gate_status"] = (
            statuses.get((engine, version), DEFAULT_GATE_STATUS)
            if engine and version
            else DEFAULT_GATE_STATUS
        )
    return rows


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/quarantine (what the repaired-but-unpublished engines measured)
#
# Registered BEFORE mount_frontend, on the same rule as every other /api route above: the SPA is
# mounted at "/", so a route added after it answers with the app shell.
#
# This is the second sink's read. It is deliberately NOT an extension of `/api/engine-health`, and
# the difference is the point of both: `/api/engine-health` says whether an engine RAN, which is a
# written ruling in `tradehub/engine_health.py` and needs no table. This one says what a repaired
# engine MEASURED, which is a fact about rows in `kalshi_quarantine_edges` and cannot be answered
# without reading them. Keeping them apart is what stops the ruling from drifting into a summary of
# whatever the table happens to hold, which would relabel a quiet engine broken and a broken one
# quiet -- the defect `engine_health` exists to prevent, arriving through the back door.
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/quarantine", tags=["Quarantine"])
def get_quarantine(
    supabase=Depends(get_supabase),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """The measured output of the quarantined Weather and Macro engines, and what of it is real.

    Every figure here comes from `tradehub/quarantine.py` and the rows, and none of it is computed
    in the client. The three counts a reader needs, and why none of them is the headline on its own:

    - **rows** -- what the scan produced. 295 on the measured run. Not a number of opportunities.
    - **opportunities** -- rows that are not a units artefact, i.e. the recommendation and the price
      on the row are the same side of the book. Still not independent opinions.
    - **independent_opportunities** -- distinct forecasts among those rows, which is the number that
      means "how many separate things did this engine actually think". 143 rows restating one GDP
      point forecast across eleven year-events is 143 rows and one opinion, and the honest headline is
      the one that says so.

    `kalshi_edges_written` is a hard `0` and is not a count of tonight's scan: there is no code path
    from a quarantined row to the trade-proposal sink. See `tradehub/quarantine.py` for the two
    independent mechanisms that hold it, and
    `tests/test_weather_macro_quarantine.py::test_the_quarantine_writes_nothing_to_the_trade_sink`
    for the proof.

    An empty table is NOT reported as `0` opportunities. A table with no rows is either a scan that
    found nothing or a migration that has not been applied, and which one it is has to be said
    rather than inferred from a count -- the same rule as `opportunities_found` on
    `/api/engine-health`, and for the same reason.
    """
    try:
        result = supabase.table("kalshi_quarantine_edges").select("*").execute()
    except Exception as exc:  # noqa: BLE001 - the one place a table read becomes an HTTP answer
        raise _table_fault("kalshi_quarantine_edges", exc) from exc

    rows = list(getattr(result, "data", None) or [])
    # Stamped by `mark_quarantine` in the scan, not recomputed here. A row's own stored
    # classification is what was measured at scan time; re-deriving it at read time would make the
    # surface's numbers depend on a rule that could change under rows nobody re-scanned.
    stamped = [dict(row, edge_kind=row.get("edge_kind"), independent=bool(row.get("independent")))
               for row in rows]

    if not stamped:
        # No rows and no classification. `rows` is 0 because the table is empty -- a real
        # measurement of an empty read -- and the OPPORTUNITY counts are null, because "no rows" is
        # not the same fact as "this engine looked and found nothing": the migration may simply not
        # be applied, and a confident 0 there would be a measurement of a search that never happened.
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "marker": QUARANTINE_MARK,
            "quarantined": True,
            "note": QUARANTINE_NOTE,
            "rows": 0,
            "measured": False,
            "unmeasured_reason": (
                "kalshi_quarantine_edges is empty, so there is nothing to classify. Either no scan "
                "has written to it, or migration "
                f"{TABLE_MIGRATIONS['kalshi_quarantine_edges']} has not been applied. This is not a "
                "count of zero opportunities: no output has been read."
            ),
            "totals": None,
            "engines": [],
            "kalshi_edges_written": 0,
            "sink": "kalshi_quarantine_edges",
            "rows_page": [],
        }

    report = quarantine_report(stamped)
    page = stamped[offset : offset + limit]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "marker": report["marker"],
        "quarantined": report["quarantined"],
        "note": report["note"],
        # The real measurement, and deliberately not called "opportunities".
        "rows": report["totals"]["rows"],
        "measured": True,
        "unmeasured_reason": None,
        "totals": report["totals"],
        "engines": report["engines"],
        "reasons": report["reasons"],
        "kalshi_edges_written": report["kalshi_edges_written"],
        "sink": report["sink"],
        "rows_page": page,
        "limit": limit,
        "offset": offset,
        "read_count": len(stamped),
        "truncated": offset + limit < len(stamped),
    }
