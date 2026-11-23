"""Screening routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from tradehub.api.dependencies import get_supabase
from tradehub.api import admin
from tradehub.workshop import store as workshop_store
from tradehub.workshop.data import UnknownSymbol
from tradehub.workshop.engine import tickers_for
from tradehub.workshop.spec import IdeaSpec



log = logging.getLogger(__name__)

from tradehub.api.routers.workshop import _fred_start
from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

router = APIRouter()
# ── Screening (Kevin, 2026-11-02 package, Part A): the composable function
# library from the screening lab, productionized. The catalog is data (the UI
# renders its controls from it; an AI emits specs in its vocabulary); a run
# executes a validated spec against the cached data layer and returns the
# table + the provenance footer (per-column source + as-of, the missing-field
# ledger, the universe cap when it bites). Missing data fails filters, never
# reads as zero. Runs are admin-gated: they spend shared free-source budget.

class _ScreenRunIn(BaseModel):
    spec: dict


@router.get("/api/screening/catalog", tags=["Screening"])
def screening_catalog():
    from tradehub.screening.cards import cards_payload
    from tradehub.screening.catalog import catalog_dict
    from tradehub.screening.universes import refresh_info

    return {**catalog_dict(), "cards": cards_payload(),
            "universe_refresh": refresh_info()}


class _ScreenIn(BaseModel):
    spec: dict
    name: str | None = None
    last_run: dict | None = None


def _run_payload(result) -> dict:
    table = result.table.copy()
    for col in table.columns:
        table[col] = table[col].astype(object).where(table[col].notna(), None)
    return {"columns": list(table.columns), "rows": table.to_dict("records"),
            "footer": result.footer}


@router.post("/api/screening/screens", tags=["Screening"], status_code=201)
def screening_create_screen(body: _ScreenIn, _admin: dict = Depends(admin.require_admin),
                            supabase=Depends(get_supabase)):
    from tradehub.screening import store as screen_store
    from tradehub.screening.spec import SpecError, validate_spec

    try:
        validate_spec(body.spec)
    except SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return screen_store.create_screen(supabase, body.name or body.spec.get("name") or "Untitled screen",
                                      body.spec, body.last_run)


@router.get("/api/screening/screens", tags=["Screening"])
def screening_list_screens(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    from tradehub.screening import store as screen_store

    rows = screen_store.list_screens(supabase)
    # The saved-screens page keeps the promote/retry action while the linked
    # idea is untracked, so the screen list carries that state too.
    tracked = {i["id"]: i.get("tracked_at")
               for i in supabase.table(workshop_store.IDEAS).select("id,tracked_at").execute().data or []}
    for row in rows:
        row["promoted_tracked_at"] = tracked.get(row.get("promoted_idea_id"))
    return rows


@router.get("/api/screening/screens/{screen_id}", tags=["Screening"])
def screening_get_screen(screen_id: int, _admin: dict = Depends(admin.require_admin),
                         supabase=Depends(get_supabase)):
    from tradehub.screening import store as screen_store

    row = screen_store.get_screen(supabase, screen_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such screen")
    return row


@router.delete("/api/screening/screens/{screen_id}", tags=["Screening"])
def screening_delete_screen(screen_id: int, _admin: dict = Depends(admin.require_admin),
                            supabase=Depends(get_supabase)):
    from tradehub.screening import store as screen_store

    if screen_store.get_screen(supabase, screen_id) is None:
        raise HTTPException(status_code=404, detail="no such screen")
    screen_store.delete_screen(supabase, screen_id)
    return {"deleted": screen_id}


@router.post("/api/screening/screens/{screen_id}/run", tags=["Screening"])
def screening_run_screen(screen_id: int, _admin: dict = Depends(admin.require_admin),
                         supabase=Depends(get_supabase)):
    """Re-run a saved screen against current data; the new run replaces the
    stored one (the run is the record the promote step consumes)."""
    from tradehub.screening import run_spec, store as screen_store
    from tradehub.screening.spec import SpecError

    row = screen_store.get_screen(supabase, screen_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such screen")
    try:
        result = run_spec(row["spec"])
    except (SpecError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = _run_payload(result)
    # The recorded survivor list is the run's FULL cohort from the footer
    # (Round 3): payload["rows"] is display-truncated whenever the spec
    # carries a limit, and a truncated list recorded here would shrink
    # the membership baseline diffed from it.
    # Round 4: the record also keeps the run's ROWS, so the saved card can
    # render the recorded results read-only. The rows are the display rows
    # the run returned -- a spec limit still caps what was displayed, and
    # the footer's survivors/displayed keep that cut honest in the view.
    last_run = {"footer": payload["footer"], "columns": payload["columns"],
                "rows": payload["rows"],
                "survivors": payload["footer"].get("survivor_tickers")
                             or [r["ticker"] for r in payload["rows"]]}
    screen_store.record_run(supabase, screen_id, last_run)
    return payload


@router.post("/api/screening/screens/{screen_id}/promote", tags=["Screening"])
def screening_promote_screen(screen_id: int, _admin: dict = Depends(admin.require_admin),
                             supabase=Depends(get_supabase)):
    """The screen -> idea handoff (lab contract; the Ideas 14/15 proxy pattern):
    the stored run's survivors become a fixed equal-weight basket, claim
    beats_benchmark vs SPY, run once, saved, published, and set to TRACKING.
    The screen's exact spec rides in the idea's provenance; a re-screen is a
    new idea, never an edit of this one. Set-once: a screen promotes once."""
    import json as _json

    from tradehub.screening import store as screen_store

    row = screen_store.get_screen(supabase, screen_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such screen")
    # Recovery lives in a dedicated field on the SCREEN (last_run.promotion),
    # never in the idea's editable plain_words: a note mentioning the key on an
    # unrelated idea must never be treated as this screen's basket. Only a
    # finished handoff -- the idea tracking -- is "already promoted".
    last_run = row.get("last_run") or {}
    key = f"[screen-promotion:{screen_id}]"
    promotion = last_run.get("promotion") or {}
    if promotion.get("key") != key:  # metadata from another screen is never identity here
        promotion = {}
    idea_id = row.get("promoted_idea_id") or promotion.get("idea_id")
    resumed = None
    if idea_id is not None:
        resumed = workshop_store.get_idea(supabase, idea_id)
        if resumed is None or resumed["idea"].get("tracked_at"):
            raise HTTPException(status_code=409, detail="this screen already promoted to an idea")
    survivors = last_run.get("survivors") or []
    if resumed is None and not survivors:
        raise HTTPException(status_code=409, detail="run the screen first -- promotion converts a run's survivors")
    footer = last_run.get("footer") or {}
    title = f"Screen basket: {row['name']}"
    plain = (f"Promoted from the screen '{row['name']}' (run {footer.get('run_at') or 'unknown'}): "
             f"its {len(survivors)} survivors as a fixed equal-weight basket -- {', '.join(survivors)}. "
             f"The screen's exact spec is preserved on the screen record; any re-screen is a new idea. "
             f"Screen spec: {_json.dumps(row['spec'], separators=(',', ':'))}")
    if resumed is None:
        idea_id = workshop_store.create_idea(supabase, title, plain)["id"]
        # Persist the ORIGINAL input before the backtest: a retry resumes this
        # basket even if the screen is re-run while the handoff is incomplete.
        screen_store.set_promotion(supabase, screen_id,
                                   {"key": key, "idea_id": idea_id, "survivors": survivors})
        screen_store.set_promoted(supabase, screen_id, idea_id)
        runs = []
    else:
        idea_id = resumed["idea"]["id"]
        if row.get("promoted_idea_id") is None:  # recovered from the dedicated field: re-link the marker
            screen_store.set_promoted(supabase, screen_id, idea_id)
        runs = resumed["runs"]

    saved = workshop_store.saved_only(runs)
    if saved:  # an earlier attempt already ran and saved: resume that run, never a second one
        run = saved[-1]
        # The original basket is in the saved run's spec, not the screen's
        # current last_run, which a re-screen may have replaced.
        survivors = (run.get("spec") or {}).get("hold") or promotion.get("survivors") or []
        return _finish_promotion(supabase, (resumed or {}).get("idea") or {}, idea_id,
                                 run, run["result"], survivors)
    unsaved = next((r for r in runs if r.get("variation") == 1), None)
    if unsaved is not None:
        # insert succeeded, save failed: save this run and finish. No backtest,
        # no second variation-1 row (the (idea_id, variation) unique constraint).
        run = workshop_store.save_run(supabase, unsaved["id"])
        survivors = (unsaved.get("spec") or {}).get("hold") or promotion.get("survivors") or []
        return _finish_promotion(supabase, (resumed or {}).get("idea") or {}, idea_id,
                                 run, unsaved["result"], survivors)
    survivors = promotion.get("survivors") or survivors
    if not survivors:
        raise HTTPException(status_code=409, detail="run the screen first -- promotion converts a run's survivors")
    spec = IdeaSpec.model_validate({"title": title, "hold": survivors,
                                    "claim": "beats_benchmark", "benchmark": "SPY"})
    try:
        prices = _api.with_rule_bars(spec, _api.workshop_closes(tickers_for(spec), spec.start), spec.start,
                                bars_fn=_api.workshop_bars)
        fred = _api.rule_series(spec, _fred_start(spec.start), fred=_api.workshop_fred, analyst_fn=_api.workshop_analyst)
    except UnknownSymbol as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = _api.run_test(spec, prices, fred, variations=1, seed=idea_id * 1000 + 1,
                      div_yields=_api.workshop_div_yields(spec, prices))
    run = workshop_store.insert_run(supabase, idea_id, 1, spec.model_dump(mode="json"), None, result)
    workshop_store.save_run(supabase, run["id"])
    return _finish_promotion(supabase, (resumed or {}).get("idea") or {}, idea_id, run, result, survivors)


def _finish_promotion(supabase, idea: dict, idea_id: int, run: dict, result: dict,
                      survivors: list[str]) -> dict:
    """Publish and track, skipping whichever an interrupted attempt already did."""
    if not idea.get("published_at"):
        workshop_store.publish(supabase, idea_id)
    if not idea.get("tracked_at"):
        workshop_store.track(supabase, idea_id, run["id"])
    return {"idea_id": idea_id, "run_id": run["id"], "verdict": result["verdict"],
            "survivors": survivors}


class _TranslateIn(BaseModel):
    query: str = Field(min_length=3, max_length=2000)


@router.post("/api/screening/translate", tags=["Screening"])
def screening_translate(body: _TranslateIn, _admin: dict = Depends(admin.require_admin)):
    """Plain English -> a validated screen spec (the spec stays visible and
    editable; translation never runs anything by itself)."""
    from tradehub.screening.translate import TranslateUnavailable, translate

    try:
        spec, model, notes = translate(body.query)
    except TranslateUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"spec": spec, "model": model, "notes": notes}


@router.post("/api/screening/run", tags=["Screening"])
def screening_run(body: _ScreenRunIn, _admin: dict = Depends(admin.require_admin)):
    from tradehub.screening import run_spec
    from tradehub.screening.spec import SpecError

    try:
        result = run_spec(body.spec)
    except SpecError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _run_payload(result)


@router.get("/api/screening/quote/{ticker}", tags=["Screening"])
def screening_quote(ticker: str, _admin: dict = Depends(admin.require_admin)):
    """Last quote + a year of closes for one result row (Kevin, 2026-11-03).
    Yahoo data, cached an hour, labelled delayed in the UI; 404 when the
    source has nothing -- never an invented price."""
    from tradehub.screening.quote import quote_payload
    from tradehub.screening.sources import DataStore

    payload = quote_payload(DataStore(), ticker.strip().upper())
    if payload is None:
        raise HTTPException(status_code=404,
                            detail=f"no quote data for {ticker.strip().upper()}")
    return payload
