"""Oil, commodities and geo routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from tradehub.api.dependencies import get_supabase
from tradehub.api.swr import SwrCache


from tradehub.api import main as _api  # call-time seam: tests patch collaborators on main

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/geo/regions/{slug}", tags=["Geo"])
def geo_region(slug: str, supabase=Depends(get_supabase)):
    """Chokepoints read API: the region's latest snapshot with every measure
    set against its trailing 30-day median (the Oil page and its map read
    this; baselines are our own snapshots, never a vendor's normal)."""
    from tradehub.geo.read import region_view

    view = region_view(supabase, slug)
    if view is None:
        raise HTTPException(status_code=404, detail="no such region")
    return view


@router.get("/api/oil/itm-record", tags=["Oil"])
def oil_itm_record(supabase=Depends(get_supabase)) -> dict:
    """How the frozen ITM line picks have done (hit rate + EV at Kalshi's
    price). Public and fail-soft: an empty record reads as zeroes.
    (Fixed 2026-11-03: this called an undefined get_client(), so the
    fail-soft branch served zeroes forever -- the record never showed.)"""
    from tradehub.oil_itm import record

    try:
        return record(supabase)
    except Exception:  # noqa: BLE001
        return {"frozen": 0, "settled": 0, "hits": 0, "hit_rate": None,
                "ev_per_dollar": None, "recent": []}


# The record below composes four live builds (oil record, shadow, blend,
# metals) and took 9-12s on EVERY hit -- the Strategies page's biggest
# single wait. The underlying decisions change on the 5-minute runner's
# cadence, so the composed payload is served stale-while-revalidate:
# visitors get the last build instantly, one background rebuild refreshes
# it, and only a cold cache ever waits (once, shared under the lock).
_FIFTEEN_RULE_CACHE = SwrCache(120)


@router.get("/api/oil/fifteen-rule", tags=["Oil"])
def oil_fifteen_rule(supabase=Depends(get_supabase)) -> dict:
    """The 15-minute trade rule's paper record (Kevin, 2026-11-05): replay and forward apart.
    Public and fail-soft: an unreadable journal reads as an empty record, never a 500."""
    try:
        return _api._FIFTEEN_RULE_CACHE.get(
            lambda: _fifteen_rule_payload(supabase, strict=True), client=supabase)
    except Exception:  # noqa: BLE001
        # A cold build failed and the cache holds no last-good payload:
        # serve the fail-soft empty record uncached, exactly as this
        # endpoint behaved before the cache existed.
        return _fifteen_rule_payload(supabase)


def _fifteen_rule_payload(supabase, *, strict: bool = False) -> dict:
    """Compose the fifteen-rule payload from its four live builds.

    Fail-soft by default (each read degrades in place, the endpoint never
    500s). With `strict=True` -- the form the SWR cache builds -- any
    failed read raises instead, so the cache keeps serving its last good
    payload rather than caching a degraded one over it."""
    from tradehub.oil_fifteen_rule import PREREG_AT, READY_TRADES, RULE, go_live_bar, record, summarize

    try:
        payload = record(supabase)
    except Exception:  # noqa: BLE001
        if strict:
            raise
        empty = summarize([])["forward"]
        payload = {"rule": RULE, "prereg_at": PREREG_AT, "ready_trades": READY_TRADES, **summarize([]),
                   "by_series": {}, "pending": 0, "recent": [], "unavailable": True,
                   "bar": go_live_bar(empty, empty)}
    # The oil minute-1 shadow variant used to ride here as an additive
    # `shadow` block; v2-oil-shadow was killed on Kevin's ruling of
    # 2026-11-17 and dropped from the page (its stored record stays in
    # its tables, readable by hand, but nothing serves it here).
    # The self-weighting blend shadow (preregistration 2026-11-11): one
    # additive block -- its fresh record, the daily weights, and the
    # promotion flag. Fail-soft the same way.
    try:
        from tradehub import fifteen_blend

        payload["blend"] = fifteen_blend.summary(supabase)
    except Exception:  # noqa: BLE001
        if strict:
            raise
    # The volatility-regime challenger (preregistration frozen 2026-11-12) and the
    # decline monitor (per day and series: live rule, blend, challenger side
    # by side). Additive and fail-soft the same way.
    try:
        from tradehub import fifteen_volregime

        payload["volregime"] = fifteen_volregime.summary(supabase)
        payload["decline"] = fifteen_volregime.decline_monitor(supabase, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001
        if strict:
            raise
    # The metals family (preregistration 2026-11-09): one additive block --
    # its own record in this payload's shape (gated by_series leading, the
    # raw reconstruction beside it), labeled as its own family and counted
    # entirely apart from the oil record above. Fail-soft the same way.
    try:
        from tradehub import metals_fifteen_rule

        payload["metals"] = metals_fifteen_rule.record(supabase)
    except Exception:  # noqa: BLE001
        if strict:
            raise
    return payload


@router.get("/api/oil/fifteen-where", tags=["Oil"])
def oil_fifteen_where() -> dict:
    """Step A: where the 15-minute models work (plan 2026-11-12).
    The study runner (tradehub.scripts.fifteen_where_run) writes the
    report JSON; this serves it fail-soft -- no file yet reads as an
    empty payload, never a 500."""
    import json

    path = os.environ.get("FIFTEEN_WHERE_PATH", "/cache/research/fifteen_where.json")
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return {}


@router.get("/api/oil/hourly-live", tags=["Oil"])
def oil_hourly_live():
    """The Commodities hero: the v1 hourly WTI model recomputed against the
    live market (tradehub/oil_live.py) -- the soonest event closing >= 20
    minutes out, our probabilities from the live price beside Kalshi's
    current mids, 20-second server cache. Display only: the graded record
    is the journal's frozen ladder, which this never touches."""
    from tradehub.oil_live import live_ladder_cached

    return live_ladder_cached()


@router.get("/api/oil/fifteen-live", tags=["Oil"])
def oil_fifteen_live():
    """The live 15-minute read for WTI, Brent and natural gas (tradehub/oil_live.py): the math the journal
    freezes, on every open window, beside Kalshi's prices. Display only; 10-second server cache."""
    from tradehub.oil_live import fifteen_live_cached

    return fifteen_live_cached()
