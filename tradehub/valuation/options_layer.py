"""Options-layer inputs (valuation Spec v1, section 3) — computed at verdict
render and stored on the verdict record. INPUTS ONLY: this module never
places, sizes, or chains an option; it states whether the frozen band geometry
admits a defined-risk debit spread and at which band strikes.

The frozen rule: in a long zone, a debit call spread (long strike at the
current band, short strike at the target band) is the expression only when the
implied move underprices the distance from the price to the target band; the
short side mirrors with a debit put spread. When the implied move already
covers the distance, the option is fairly priced — stock expression only.
No naked shorts, no premium selling; max loss on any sketched spread is the
debit, by construction.
"""
from __future__ import annotations

import math

LONG_ZONES = ("buy_zone", "buy_zone_strong")
SHORT_ZONES = ("short_zone", "short_zone_strong")


def _bands_sorted(bands: dict) -> list[tuple[str, float]]:
    return [("bear", float(bands["bear"])), ("base", float(bands["base"])),
            ("bull", float(bands["bull"]))]


def spread_inputs(*, price: float | None, bands: dict | None, zone: str | None,
                  implied_move_pct: float | None) -> dict:
    """The options inputs for one fact sheet. implied_move_pct is in percent
    (the price layer's convention: ATM straddle / spot x 100)."""
    # A non-finite read is "no data", not a number: NaN compares False
    # against every distance (reading as "the move covers the distance")
    # and is not JSON-encodable, which crashed verdict storage live
    # (AMGN, 2026-11-12). Treat it exactly like a missing read.
    if implied_move_pct is not None and not math.isfinite(implied_move_pct):
        implied_move_pct = None
    out: dict = {
        "implied_move_pct": implied_move_pct,
        "expression": "none",
        "direction": None,
        "long_strike": None,
        "short_strike": None,
        "current_band": None,
        "target_band": None,
        "target_price": None,
        "distance_to_target_pct": None,
        "underpriced": None,
        "expiry_basis": ("set by the falsifier/print calendar at expression "
                         "time; inputs only in v1"),
        "max_loss": "the debit (defined risk)",
        "reason": None,
    }
    if price is None or not bands or zone in (None, "no_bands", "stale",
                                              "no_price"):
        out["reason"] = "no live bands to price an expression against"
        return out
    if zone in LONG_ZONES:
        direction = "long"
    elif zone in SHORT_ZONES:
        direction = "short"
    else:
        out["reason"] = f"zone {zone} carries no directional expression"
        return out
    out["direction"] = direction
    ordered = _bands_sorted(bands)
    if direction == "long":
        # Current band: the highest band at or below the price (the bear band
        # when the price sits under all three); target: the next band above.
        below = [(name, val) for name, val in ordered if val <= price]
        cur_name, cur_val = below[-1] if below else ordered[0]
        above = [(name, val) for name, val in ordered if val > cur_val]
        if not above:
            out["reason"] = "no band above the current band to target"
            return out
        tgt_name, tgt_val = above[0]
        distance = (tgt_val - price) / price * 100.0
        expression = "debit_call_spread"
    else:
        # Mirror: current band is the lowest band at or above the price (the
        # bull band when the price sits over all three); target below it.
        above = [(name, val) for name, val in ordered if val >= price]
        cur_name, cur_val = above[0] if above else ordered[-1]
        below = [(name, val) for name, val in ordered if val < cur_val]
        if not below:
            out["reason"] = "no band below the current band to target"
            return out
        tgt_name, tgt_val = below[-1]
        distance = (price - tgt_val) / price * 100.0
        expression = "debit_put_spread"
    out.update({
        "current_band": cur_name, "target_band": tgt_name,
        "target_price": tgt_val,
        "distance_to_target_pct": round(distance, 4),
    })
    if implied_move_pct is None:
        out["expression"] = "unevaluated"
        out["reason"] = "no implied move available for this name"
        return out
    out["underpriced"] = bool(implied_move_pct < distance)
    if out["underpriced"]:
        out["expression"] = expression
        out["long_strike"] = cur_val
        out["short_strike"] = tgt_val
    else:
        out["expression"] = "stock_only"
        out["reason"] = ("the implied move already covers the distance to "
                         "the target band — the option is fairly priced")
    return out


def gather(ds, ticker: str, sheet: dict) -> dict:
    """spread_inputs with the implied move pulled from the price layer.
    A missing/failed implied-move read is recorded as unevaluated, never
    estimated."""
    try:
        implied = ds.implied_move(ticker)
    except Exception:  # noqa: BLE001 -- absence is data, not a crash
        implied = None
    return spread_inputs(price=sheet.get("price"), bands=sheet.get("bands"),
                         zone=sheet.get("baseline_verdict"),
                         implied_move_pct=implied)
