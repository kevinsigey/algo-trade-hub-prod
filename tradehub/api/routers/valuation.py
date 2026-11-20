"""Valuation and guidance routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
import re
import threading
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tradehub.api.dependencies import get_supabase
from tradehub.api import admin



log = logging.getLogger(__name__)

router = APIRouter()


def _snapshot_stamp(snap: dict | None) -> dict | None:
    if snap is None:
        return None
    return {"id": snap.get("id"), "computed_at": snap.get("computed_at"),
            "completed_at": snap.get("completed_at"),
            "sheet_count": snap.get("sheet_count"),
            "banded_count": snap.get("banded_count"),
            "source": snap.get("source")}


@router.get("/api/valuation-bands", tags=["Valuation"])
def valuation_bands_list(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """The latest COMPLETED snapshot's fact sheets, stamped (reliability
    pass F1): one compute's dataset served whole under its snapshot id +
    computed-at -- a recompute in flight never swaps figures under the
    reader. snapshot is null only for pre-fix legacy data, and the page
    says so rather than inventing a version. Display data only."""
    from tradehub.valuation import store as val_store

    snap, sheets = val_store.latest_snapshot_sheets(supabase)
    # Re-presentation build: ONE additive summary block (verdict strip,
    # attention feed, board markers), computed from persisted history
    # of COMPLETED snapshots only. A summary failure must never take
    # the sheets down -- the block reads null and the page says so.
    summary = None
    try:
        from tradehub.valuation import page_summary

        summary = page_summary.build_summary(supabase)
    except Exception:  # noqa: BLE001 -- sheets are the payload; summary is additive
        summary = None
    # Guidance rebuild (2026-11-16 brief): ONE more additive block — the
    # movers / football-field grid / missing-band board. Same fail-soft
    # rule: a board failure reads null, never takes the sheets down.
    board = None
    try:
        from tradehub.valuation import guidance_page

        board = guidance_page.build_board(
            supabase, snapshot_id=snap["id"] if snap else None)
    except Exception:  # noqa: BLE001 -- additive block
        board = None
    return {"snapshot": _snapshot_stamp(snap), "sheets": sheets,
            "summary": summary, "board": board}


@router.get("/api/valuation-bands/{ticker}", tags=["Valuation"])
def valuation_bands_get(ticker: str, _admin: dict = Depends(admin.require_admin),
                        supabase=Depends(get_supabase)):
    from tradehub.valuation import store as val_store

    snap, _sheets = val_store.latest_snapshot_sheets(supabase)
    row = None
    if snap is not None:
        row = val_store.snapshot_sheet(supabase, snap["id"],
                                       ticker.strip().upper())
    if row is None:
        row = val_store.latest_sheet(supabase, ticker.strip().upper())
    if row is None:
        raise HTTPException(status_code=404, detail="no fact sheet for ticker")
    view = val_store.with_peer_members(row)
    view["snapshot"] = _snapshot_stamp(snap)
    return view


# ── Valuation verdicts (Phase 1: the forked debate over Exhibit A) ─────────
# Display-only by the spec's authority rule: verdicts render, log, and grade
# against the band-rule baseline and the proposer's own pick; nothing here
# feeds an idea, a book, or an order, and this module has no path to any.

def _verdict_view(supabase, row: dict) -> dict:
    from tradehub.valuation import verdict_store

    view = dict(row)
    view["zone"] = row.get("baseline_verdict")
    grades = verdict_store.grades_for(supabase, row["id"])
    gview: dict = {}
    for horizon in (20, 60):
        match = next((g for g in grades if g.get("horizon") == horizon), None)
        if match is None:
            gview[str(horizon)] = "pending"
        else:
            gview[str(horizon)] = {
                "peer_excess_pct": match.get("peer_excess_pct"),
                "index_excess_pct": match.get("index_excess_pct"),
                "relative_pass": match.get("verdict_relative_pass"),
                "brier": match.get("verdict_brier"),
                "baseline_relative_pass": match.get("baseline_relative_pass"),
                "proposer_relative_pass": match.get("proposer_relative_pass"),
                "mfe_pct": match.get("mfe_pct"),
                "mae_pct": match.get("mae_pct"),
                "time_to_target_days": match.get("time_to_target_days"),
            }
    view["grades"] = gview
    return view


@router.get("/api/valuation-verdicts", tags=["Valuation"])
def valuation_verdicts_list(_admin: dict = Depends(admin.require_admin),
                            supabase=Depends(get_supabase)):
    """Latest rendered verdict per ticker, the authority-gate summary, the
    band watch's held-position flags, and the pending trigger queue."""
    from tradehub.valuation import grading, verdict_store

    views = [_verdict_view(supabase, r)
             for r in verdict_store.latest_verdicts(supabase)
             if r.get("status") == "rendered"]
    flags = [s["state"] for s in verdict_store.all_watch_state(supabase)
             if s.get("kind") == "held" and s.get("state")]
    return {
        "chip": "Valuation debate — display only; graded against the band "
                "rule and the proposer's own pick, never a model signal",
        "authority": grading.authority_summary(
            verdict_store.all_grades(supabase)),
        "verdicts": views,
        "watch": {"flags": flags,
                  "pending_triggers": verdict_store.pending_triggers(supabase)},
    }


@router.get("/api/valuation-verdicts/{ticker}", tags=["Valuation"])
def valuation_verdicts_history(ticker: str,
                               _admin: dict = Depends(admin.require_admin),
                               supabase=Depends(get_supabase)):
    """Every verdict row for a name, voids included — the audit trail."""
    from tradehub.valuation import verdict_store

    rows = verdict_store.verdicts_for(supabase, ticker.strip().upper())
    return [_verdict_view(supabase, r) for r in rows]


class _VerdictRunIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=12)
    force: bool = False  # rerun even inside the reuse window


# Same daily-cadence discipline as the classic debates: a rerun inside the
# window returns the standing verdict instead of spending another panel.
_VERDICT_REUSE_WINDOW = timedelta(hours=12)
_VERDICT_IN_FLIGHT: set[str] = set()
_VERDICT_LOCK = threading.Lock()


@router.post("/api/valuation-verdicts/run", tags=["Valuation"], status_code=202)
def valuation_verdict_run(body: _VerdictRunIn,
                          _admin: dict = Depends(admin.require_admin),
                          supabase=Depends(get_supabase)):
    """Start an on-demand valuation debate (spec section 5). The fact sheet
    is recomputed for the name, then the forked debate renders a verdict off
    it. Declines that can be known up front — no sheet, no bands, a stale
    sheet, the daily budget spent — answer 422 with the reason; the render
    itself runs on a background thread and lands in the feed."""
    from tradehub.valuation import store as val_store
    from tradehub.valuation import verdict_store
    from tradehub.valuation import verdicts as val_verdicts

    ticker = body.ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", ticker):
        raise HTTPException(status_code=422, detail="that does not look like a ticker")
    sheet = val_store.latest_sheet(supabase, ticker)
    if sheet is None:
        raise HTTPException(status_code=422, detail=f"no fact sheet for {ticker} — "
                                                    "the name has no recorded guidance")
    if sheet.get("status") != "banded" or not sheet.get("bands"):
        raise HTTPException(status_code=422, detail=f"{ticker} has no bands "
                                                    f"(sheet status {sheet.get('status')})")
    if sheet.get("stale"):
        raise HTTPException(status_code=422, detail=f"{ticker}'s fact sheet is stale — "
                                                    "a stale sheet does not render a verdict")
    now = datetime.now(timezone.utc)
    if val_verdicts.cap_reached(supabase, now):
        raise HTTPException(status_code=422, detail="the daily debate budget "
                                                    f"({val_verdicts.DAILY_CAP}/day) is spent")
    if not body.force:
        for row in verdict_store.verdicts_for(supabase, ticker):
            if row.get("status") != "rendered":
                continue
            try:
                ran_at = datetime.fromisoformat(
                    str(row["rendered_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                break
            age = now - ran_at
            if age < _VERDICT_REUSE_WINDOW:
                return JSONResponse(status_code=200, content={
                    "reused": row["id"], "ticker": ticker,
                    "age_hours": round(age.total_seconds() / 3600, 1)})
            break
    with _VERDICT_LOCK:
        if ticker in _VERDICT_IN_FLIGHT:
            raise HTTPException(status_code=409, detail=f"a valuation debate on {ticker} "
                                                        "is already running")
        _VERDICT_IN_FLIGHT.add(ticker)

    def _go() -> None:
        try:
            from tradehub.screening.sources import DataStore
            from tradehub.valuation import run as val_run

            ds = DataStore()
            try:
                val_run.compute(supabase, ds, only=ticker)
            except Exception:  # noqa: BLE001 -- the stored sheet still stands
                pass
            val_verdicts.render_verdict(supabase, ds, ticker,
                                        trigger="on_demand")
        finally:
            with _VERDICT_LOCK:
                _VERDICT_IN_FLIGHT.discard(ticker)

    threading.Thread(target=_go, daemon=True,
                     name=f"valuation-debate-{ticker}").start()
    return {"started": ticker}


# ── Band crossings (Spec C, log-only) ────────────────────────────────────────
# The engine records would-be actions against the Guidance bands and grades
# them; it has no order path. This endpoint is its read surface: the mode
# stated up front, the falsifier counter, recent scans, recent crossings.

@router.get("/api/band-crossings", tags=["Valuation"])
def band_crossings_list(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """Recent band crossings with their would-be actions, Portfolio Check
    outcomes, and graded results, plus the engine's mode and falsifier
    state. Read-only; the engine itself is log-only (Kevin, 2026-11-09)."""
    from tradehub.valuation import band_crossing as bc

    return bc.read_surface(supabase)


# ── Level watcher (Spec D, Stage 1 — Rung 1 alerts only) ───────────────────
# The watcher evaluates price levels with conditions and alerts; Stage 1
# has no order path. This endpoint is its read surface: stage and rung
# cap stated up front, watcher health from the heartbeat record, the
# watches, the trigger log, pending alerts (the outbox an agent-side
# poller carries into the Trading Thesis Testing chat), family grading,
# and the governor state.

@router.get("/api/level-watcher", tags=["Valuation"])
def level_watcher_surface(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    """The Level Watcher's state: health, watches, trigger log, alert
    outbox, grading families, governors. Read-only; Stage 1 is
    alert-only (Kevin, 2026-11-09)."""
    from tradehub import level_watcher as lw

    return lw.read_surface(supabase)


# ── Debate candidates + the per-name decision view (Loop Batch 2) ──────────
# Candidates are generated from RECORDED screen runs/membership and the
# latest completed snapshot's band history — never ad-hoc builder runs.
# The decision view is one read surface per name: fact sheet, systems,
# judgment, named gaps. Display-only, like the rest of the layer.

@router.get("/api/debate-candidates", tags=["Valuation"])
def debate_candidates_list(_admin: dict = Depends(admin.require_admin),
                           supabase=Depends(get_supabase)):
    """The persisted candidate queue for the latest completed snapshot:
    counts by source class (entrants / zone names / conjunctions) and the
    queue rows with their sources and states."""
    from tradehub.valuation import candidates as cand_mod
    from tradehub.valuation import store as val_store

    snap = val_store.latest_snapshot(supabase)
    if snap is None:
        return {"snapshot": None, "counts": {"entrants": 0, "zone_names": 0,
                                             "conjunctions": 0, "total": 0},
                "candidates": [], "excluded": [],
                "pending_by_class": {"conjunction": 0, "entrant": 0,
                                     "zone": 0},
                "generated_at": None}
    rows = cand_mod.candidates_for_snapshot(supabase, snap["id"])
    counts = {
        "entrants": sum(1 for r in rows if (r.get("sources") or {})
                        .get("entrants")),
        "zone_names": sum(1 for r in rows if (r.get("sources") or {})
                          .get("zone")),
        "conjunctions": sum(1 for r in rows
                            if r.get("candidate_class") == "conjunction"),
        "total": len(rows)}
    # Round 4: the aggregate queue view -- pending counts by class, the
    # persisted named exclusions, and the generation stamp (scar tissue
    # #9: the panel serves stamped data, never a silent live recompute).
    excluded = cand_mod.exclusions_for_snapshot(supabase, snap["id"])
    pending_by_class = {cls: sum(1 for r in rows
                                  if r.get("candidate_class") == cls
                                  and r.get("state") == "pending")
                        for cls in ("conjunction", "entrant", "zone")}
    generated = [r.get("computed_at") for r in rows + excluded
                 if r.get("computed_at")]
    return {"snapshot": _snapshot_stamp(snap), "counts": counts,
            "candidates": rows, "excluded": excluded,
            "pending_by_class": pending_by_class,
            "generated_at": max(generated) if generated else None}


# One candidate drain at a time (CodeRabbit on #575): two overlapping drains
# could both read the same pending candidate and render its debate twice.
# ponytail: in-process lock; the API runs one uvicorn worker (Dockerfile CMD).
# A second worker would need a row claim (pending -> rendering) instead.
_DRAIN_LOCK = threading.Lock()


def _drain_candidates(supabase, ds) -> bool:
    """Run one drain unless another is in flight; False when skipped. A skipped
    request loses nothing: the running drain works the same pending queue, and
    a capacity decline still leaves candidates pending for the next run."""
    from tradehub.valuation import candidates as cand_mod

    if not _DRAIN_LOCK.acquire(blocking=False):
        return False
    try:
        cand_mod.run_candidate_debates(supabase, ds)
    finally:
        _DRAIN_LOCK.release()
    return True


@router.post("/api/debate-candidates/run", tags=["Valuation"], status_code=202)
def debate_candidates_run(_admin: dict = Depends(admin.require_admin),
                          supabase=Depends(get_supabase)):
    """Generate candidates from the recorded flow, then drain the queue
    into debate renders on a background thread (shared daily budget,
    fail-closed LLM chain — a capacity decline leaves candidates pending
    and stores nothing). Returns the generation summary immediately."""
    from tradehub.valuation import candidates as cand_mod

    summary = cand_mod.generate_candidates(supabase)

    def _go() -> None:
        from tradehub.screening.sources import DataStore

        _drain_candidates(supabase, DataStore())

    threading.Thread(target=_go, daemon=True,
                     name="debate-candidates-drain").start()
    return {"generation": {k: summary[k] for k in
                           ("snapshot", "counts", "inserted", "excluded")}}


@router.get("/api/verdict-chips", tags=["Valuation"])
def verdict_chips_list(_admin: dict = Depends(admin.require_admin),
                       supabase=Depends(get_supabase)):
    """The compact per-name verdict read for the pages: latest rendered
    verdict per ticker (verdict, confidence, dissent, judge identity,
    exhibit snapshot id). Names without a rendered verdict are absent —
    the pages render that absence honestly, never a placeholder."""
    from tradehub.valuation import decisions

    return {"generated_at": datetime.now(timezone.utc).isoformat(),
            "chips": decisions.verdict_chips(supabase)}


@router.get("/api/name-decision/{ticker}", tags=["Valuation"])
def name_decision_get(ticker: str,
                      _admin: dict = Depends(admin.require_admin),
                      supabase=Depends(get_supabase)):
    """One name's decision view: what we know (fact sheet), what the
    systems say (recorded screens, zone, crossings, print classification),
    the judgment (debate verdict + falsifier standing), and what is
    missing — named gaps, never proxied. 404 when the hub knows nothing
    about the name at all."""
    from tradehub.valuation import decisions

    view = decisions.name_decision(supabase, ticker)
    if view is None:
        raise HTTPException(status_code=404,
                            detail="nothing on record for that name")
    return view
