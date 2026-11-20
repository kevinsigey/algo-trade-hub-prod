"""System, admin and engine-health routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from tradehub.api.schemas import (
    HealthResponse,
)
from tradehub.api.dependencies import get_supabase
from tradehub.api import admin
from tradehub.engine_health import engine_health


from tradehub.api.shared import (
    _snapshot,
)
from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse, tags=["System"])
def health(supabase=Depends(get_supabase)):
    """Liveness plus a read-only health report. Returns 200 if the API process is running.

    `status` stays the liveness answer so nothing that depended on it breaks. `report` is the detail:
    timer freshness, per-family freeze counts, order-book age.

    Synchronous on purpose: `_api.collect_health` does blocking Supabase reads and an `rglob` over the
    order-book directory, and doing those on the event loop would stall every other request for the
    duration. FastAPI runs a `def` handler in its threadpool.

    It never raises. A missing table or absent credentials degrade the affected fact to `never` /
    `missing` rather than the whole report to a 500, because "no data" is itself the thing an operator
    needs to see, and a reader shown an error page cannot tell it from a broken query.
    """
    snap = _snapshot("health")
    if snap is not None:
        built = datetime.fromisoformat(str(snap["built_at"]).replace("Z", "+00:00"))
        return HealthResponse(status="ok", timestamp=built,
                              report=_api.public_health_report(snap["payload"]))
    now = datetime.now(timezone.utc)
    return HealthResponse(status="ok", timestamp=now,
                          report=_api.public_health_report(_api.collect_health(supabase, now=now)))


@router.get("/api/health/full", response_model=HealthResponse, tags=["System"])
def health_full(supabase=Depends(get_supabase), _admin: dict = Depends(admin.require_admin)):
    """The complete health report, history matrices included -- the Health
    page's payload, admin-gated since the item-6 trim took the internals off
    the public endpoint."""
    snap = _snapshot("health")
    if snap is not None:
        built = datetime.fromisoformat(str(snap["built_at"]).replace("Z", "+00:00"))
        return HealthResponse(status="ok", timestamp=built, report=snap["payload"])
    now = datetime.now(timezone.utc)
    return HealthResponse(status="ok", timestamp=now, report=_api.collect_health(supabase, now=now))


class _RerunIn(BaseModel):
    job: str


@router.post("/api/health/rerun", tags=["System"])
def health_rerun(body: _RerunIn, _admin: dict = Depends(admin.require_admin)):
    """Ask the host to re-run scan or settle (phase-2 §4.3). The API cannot start host
    jobs, so this drops a trigger file the VPS watcher claims within a minute; the file
    carries the asking admin's email and the time, and the run lands in scanner_runs.
    One pending request per job -- a second ask returns the one already waiting."""
    from tradehub import health_rerun
    try:
        return health_rerun.request_rerun(body.job, requested_by=_admin.get("email") or "admin",
                                          now=datetime.now(timezone.utc))
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except health_rerun.RerunUnavailable as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.get("/api/health/rerun", tags=["System"])
def health_rerun_pending(_admin: dict = Depends(admin.require_admin)):
    from tradehub import health_rerun
    return {"pending": health_rerun.pending()}


@router.get("/api/admin/me", tags=["Admin"])
def get_admin_me(user: dict = Depends(admin.require_admin)) -> dict:
    """Kevin's session, confirmed server-side. The Workshop's routes use the same dependency."""
    return user


# ── Machine API keys (phase-2 spec §1, step 1): issue/revoke from the admin UI only. ──────
# No /api/v1 routes exist yet -- this step is the key lifecycle and the audit table, shipped
# dark. The plaintext key is returned exactly once, by create; only its hash is stored, and
# no response ever carries the hash.
class _KeyIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    scopes: list[str] = Field(min_length=1)
    max_qty: int = Field(default=100, ge=1, le=100_000)
    max_notional: float = Field(default=25_000, gt=0)
    daily_cap: int = Field(default=50, ge=1, le=10_000)
    book: str = "main"


@router.post("/api/admin/keys", tags=["Admin"], status_code=201)
def create_machine_key(body: _KeyIn, _admin: dict = Depends(admin.require_admin),
                       supabase=Depends(get_supabase)):
    from tradehub.api import machine_keys

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    try:
        row, plaintext = machine_keys.create_key(
            supabase, body.label, body.scopes, max_qty=body.max_qty,
            max_notional=body.max_notional, daily_cap=body.daily_cap, book=body.book)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**row, "key": plaintext}


@router.get("/api/admin/keys", tags=["Admin"])
def list_machine_keys(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    from tradehub.api import machine_keys

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"keys": machine_keys.list_keys(supabase)}


@router.post("/api/admin/keys/{key_id}/revoke", tags=["Admin"])
def revoke_machine_key(key_id: int, _admin: dict = Depends(admin.require_admin),
                       supabase=Depends(get_supabase)):
    from tradehub.api import machine_keys

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    row = machine_keys.revoke_key(supabase, key_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such key")
    return row


@router.get("/api/admin/keys/{key_id}/events", tags=["Admin"])
def machine_key_events(key_id: int, _admin: dict = Depends(admin.require_admin),
                       supabase=Depends(get_supabase)):
    from tradehub.api import machine_keys

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    if machine_keys.get_key(supabase, key_id) is None:
        raise HTTPException(status_code=404, detail="no such key")
    return {"events": machine_keys.recent_events(supabase, key_id)}


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/engine-health (which edge types are fed by a STOPPED engine)
#
# Registered BEFORE mount_frontend below: the SPA is mounted at "/", so a route added after it is
# shadowed and this endpoint would answer with the app shell. Same ordering rule as
# /api/scoreboard and /api/jobs-scorecard above.
#
# No database, and that is the design rather than a shortcut. This endpoint's subject is whether an
# engine RAN, and whether an engine ran is a written ruling, not a fact about a table: nothing in
# `kalshi_edges` distinguishes "the engine looked and found nothing" from "the engine never got as
# far as looking", because in the second case there is no row to look at. Inferring the state from
# the absence of rows would be the defect restated one layer up -- a quiet board relabelled broken
# the first time a market was thin, and a broken engine relabelled quiet every time it was quiet by
# accident. So the ruling is `engine_health` (pure, in the same language as the engines it rules
# on) and the counts that describe it are computed here rather than in the page.
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/engine-health", tags=["Engine Health"])
def get_engine_health():
    """Which of this product's edge types are fed by an engine that cannot run, and why.

    The defect this exists for: Kalshi's API stopped sending `yes_ask`, and the Tier-1 real-edge
    weather and macro engines still read it with a `0` default. Every market they fetch reads as a
    0c quote, so they skip all of them, publish nothing and raise nothing -- the failure is closed,
    which is why nothing was ever written that was wrong. What was wrong was the DISPLAY: the
    Weather tab rendered "No high-confidence edges detected in weather", and that is a finding. It
    was never looked for. The same ambiguity was already ruled on for CPI, where a withheld row
    that vanished silently read as an engine that had been retired
    (`market_sentiment_tool/src/lib/displayOnlyEngines.ts`); this is the same rule for a run that
    produces no row to withhold.

    A reader has to be able to tell three things apart, and only two of them are this endpoint's
    business:

      * an engine that RAN and found nothing -- a measurement, and the empty board is the finding;
      * an engine that COULD NOT RUN -- nothing was measured, and this endpoint says so;
      * a read that FAILED -- nothing is known at all, which the board already renders separately
        (`edgesError` in the Prediction Lab) and which this endpoint does not participate in,
        because it reads no table and so cannot fail.

    Every edge type in `engine_health.EDGE_TYPES` appears in the response, in one state or the
    other, and the counts are computed here: `edge_types_could_not_run` is a subtraction on a set,
    and a component that does it at render time is a rule in a second language with no test on it.

    `opportunities_found` is present and null on every entry. Not an unfinished field: this
    endpoint reports whether an engine ran, and a count of what it found belongs to the read of the
    ledger, which is a different read over a different bound. A null here is the machine-readable
    half of "nothing was measured" -- and for a stopped engine, `0` would be the single most
    damaging value in the product, because it would read as a search that ran and found nothing.
    """
    return {"as_of": datetime.now(timezone.utc).isoformat(), **engine_health()}
