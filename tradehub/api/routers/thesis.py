"""Thesis Tracker routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from tradehub.api.dependencies import get_supabase
from tradehub.api import admin
from tradehub.gate_status import table_missing


from tradehub.api.shared import (
    _table_fault,
)

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/thesis/cards", tags=["Thesis Tracker"])
def get_thesis_cards(supabase=Depends(get_supabase),
                     _admin: dict = Depends(admin.require_admin)):
    """The frozen forecast cards, newest first, superseded ones marked.
    A missing table (pre-migration deploy) serves an empty list rather
    than a 500 -- the page's true statement then is 'no cards yet'."""
    from tradehub.tracker import cards

    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        rows = cards.list_cards(supabase)
    except Exception as exc:  # noqa: BLE001 - classified below
        if table_missing(exc, "forecast_cards"):
            return {"cards": []}
        raise _table_fault("forecast_cards", exc) from exc
    return {"cards": rows}


@router.get("/api/thesis/scoreboard", tags=["Thesis Tracker"])
def get_thesis_scoreboard(supabase=Depends(get_supabase),
                          _admin: dict = Depends(admin.require_admin)):
    """The tracker scoreboard (PR 7): per-claim progress with the
    grader's own math, per-play-kind P&L, the regime panel, the
    cash-floor gauge and the breach log, as one read model. ADMIN ONLY
    (Claude's post-merge review of #552, 2026-11-16): the board carries
    the order-route refusal log with key ids, the sizing config and
    live cash percentages -- it shipped without the dependency and
    served 200 signed-out. A missing tracker table (pre-migration
    deploy) serves a null board rather than a 500 -- the page's true
    statement then is 'not seeded yet'."""
    from tradehub.tracker import scoreboard

    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    try:
        board = scoreboard.build_scoreboard(supabase)
    except Exception as exc:  # noqa: BLE001 - classified below
        if table_missing(exc, "theses"):
            return {"scoreboard": None}
        raise _table_fault("theses", exc) from exc
    return {"scoreboard": board}
