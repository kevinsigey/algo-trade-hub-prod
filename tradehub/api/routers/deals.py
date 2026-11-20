"""Deals and IPOs routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from tradehub.api.dependencies import get_supabase
from tradehub.api import admin



log = logging.getLogger(__name__)

router = APIRouter()


# ── Deals and IPOs (Part B): the two builders. A run computes from the inputs
# as entered and saves inputs + outputs as the record; the AI summary is a
# labelled draft written back onto the same row. ──
class _DealRunIn(BaseModel):
    inputs: dict


@router.post("/api/deals/ipo/run", tags=["Deals"], status_code=201)
def deals_ipo_run(body: _DealRunIn, _admin: dict = Depends(admin.require_admin),
                  supabase=Depends(get_supabase)):
    from tradehub.deals import store as deal_store
    from tradehub.deals.ipo import DealInputError, run_ipo

    try:
        outputs = run_ipo(body.inputs)
    except DealInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return deal_store.save_run(supabase, "ipo", body.inputs.get("company") or "IPO", body.inputs, outputs)


@router.post("/api/deals/ma/run", tags=["Deals"], status_code=201)
def deals_ma_run(body: _DealRunIn, _admin: dict = Depends(admin.require_admin),
                 supabase=Depends(get_supabase)):
    from tradehub.deals import store as deal_store
    from tradehub.deals.ipo import DealInputError
    from tradehub.deals.ma import run_ma

    try:
        outputs = run_ma(body.inputs)
    except DealInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    name = f"{(body.inputs.get('acquirer') or {}).get('name', 'Acquirer')} / {(body.inputs.get('target') or {}).get('name', 'Target')}"
    return deal_store.save_run(supabase, "ma", name, body.inputs, outputs)


@router.get("/api/deals/runs", tags=["Deals"])
def deals_list_runs(_admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    from tradehub.deals import store as deal_store

    return deal_store.list_runs(supabase)


@router.get("/api/deals/runs/{run_id}", tags=["Deals"])
def deals_get_run(run_id: int, _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    from tradehub.deals import store as deal_store

    row = deal_store.get_run(supabase, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such deal run")
    return row


@router.post("/api/deals/runs/{run_id}/summary", tags=["Deals"])
def deals_summary(run_id: int, _admin: dict = Depends(admin.require_admin), supabase=Depends(get_supabase)):
    from tradehub.deals import store as deal_store
    from tradehub.deals.summary import SummaryUnavailable, draft_summary

    row = deal_store.get_run(supabase, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no such deal run")
    try:
        doc, model = draft_summary(row["kind"], row["name"], row["inputs"], row["outputs"])
    except SummaryUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return deal_store.set_summary(supabase, run_id, doc, model)


@router.get("/api/deals/public/{ticker}", tags=["Deals"])
def deals_public(ticker: str, source: str = "yahoo", _admin: dict = Depends(admin.require_admin)):
    """Prefill a public company's side of the M&A form: market data (Yahoo)
    or the company's own filed 10-K numbers (EDGAR), both as-of stamped."""
    from tradehub.deals.public import edgar_company, public_company

    try:
        if source == "edgar":
            return edgar_company(ticker.upper())
        return public_company(ticker.upper())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
