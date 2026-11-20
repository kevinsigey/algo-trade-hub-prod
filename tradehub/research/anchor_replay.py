"""Step 17: the anchor replay -- daily natural gas and Brent re-centred on the
latest Kalshi 15-minute strike (the free read of the Pyth index).

Preregistration: docs/superpowers/specs/2026-11-19-anchor-replay-prereg.md
(frozen before the run). Pure computation over injected rows, strikes and
candles; the runner (scripts/anchor_replay_run.py) does the reading. The
honesty pins: a row is scored only if its stored probability recomputes
from its frozen payload (the sanity gate), and only the centre moves --
every other stored input is reused exactly.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.engines.natgas_daily import GAS_RESOLUTION
from tradehub.engines.oil import OIL_RESOLUTION
from tradehub.fifteen_volregime import clustered_low95
from tradehub.markets import prob_in_interval

_ET = ZoneInfo("America/New_York")
MATCH_TOL = 2e-5   # the journal stores probabilities to 5 decimal places (prereg amendment)
FLOOD_SHARE = 0.05

SERIES = {
    "natgas_daily": {"version": "natgas-v1", "fifteen_series": "KXNATGAS15M",
                     "coin": "xyz:NATGAS", "resolution": GAS_RESOLUTION},
    "oil_brent": {"version": "brent-v1", "fifteen_series": "KXBRENT15M",
                  "coin": "xyz:BRENTOIL", "resolution": OIL_RESOLUTION},
}


def strike_from_target(target: str) -> float:
    return float(target.rsplit("-T", 1)[1])


def yes_interval_greater(strike: float, resolution: float) -> tuple[float, float]:
    """The YES interval of a 'greater' strike at the engine's resolution --
    markets.yes_interval's rule, rebuilt from the ticker alone."""
    return (strike + resolution / 2.0, math.inf)


def _brent_mu(payload: dict, level: float) -> float:
    x = payload["cl_change_5"] or 0.0
    return level + payload["horizon_days"] * (payload["alpha"] + payload["beta"] * x)


def recompute_original(forecaster: str, payload: dict, interval) -> float:
    if forecaster == "natgas_daily":
        return prob_in_interval(payload["live_price"], payload["sigma_eff"], interval)
    return prob_in_interval(_brent_mu(payload, payload["last_settlement"]),
                            payload["sigma"] * math.sqrt(payload["horizon_days"]), interval)


def variant_prob(forecaster: str, payload: dict, interval, anchor: float) -> float:
    if forecaster == "natgas_daily":
        return prob_in_interval(anchor, payload["sigma_eff"], interval)
    return prob_in_interval(_brent_mu(payload, anchor),
                            payload["sigma"] * math.sqrt(payload["horizon_days"]), interval)


MAX_TAPE_AGE = timedelta(minutes=2)


def perp_at(tape: list[tuple[datetime, float]], instant: datetime) -> float | None:
    """The stored tape's price at `instant`: the last point at or before it,
    at most MAX_TAPE_AGE old -- a staler read is no read."""
    times = [t for t, _p in tape]
    idx = bisect_right(times, instant) - 1
    if idx < 0 or instant - tape[idx][0] > MAX_TAPE_AGE:
        return None
    return tape[idx][1]


def anchor(strike: float, window_open: datetime, tape, frozen_at: datetime) -> float | None:
    """strike + the perp's move since the strike's window opened."""
    at_open = perp_at(tape, window_open)
    at_freeze = perp_at(tape, frozen_at)
    if at_open is None or at_freeze is None:
        return None
    return strike + (at_freeze - at_open)


def _brier(prob: float, outcome: int) -> float:
    return (prob - outcome) ** 2


def build_report(rows_by_series: dict, strikes_by_series: dict, tape_by_series: dict) -> dict:
    series_out: dict[str, dict] = {}
    for forecaster, rows in rows_by_series.items():
        spec = SERIES[forecaster]
        strikes = sorted(strikes_by_series.get(forecaster, []))
        opens = [w for w, _s in strikes]
        tape = tape_by_series.get(forecaster, [])
        scored = mismatch = no_strike = no_candle = 0
        briers = {"original": [], "variant": [], "market": []}
        diffs: list[tuple[str, float]] = []
        for row in rows:
            interval = yes_interval_greater(strike_from_target(row["target"]), spec["resolution"])
            if abs(recompute_original(forecaster, row["payload"], interval)
                   - row["probability"]) > MATCH_TOL:
                mismatch += 1
                continue
            idx = bisect_right(opens, row["frozen_at"]) - 1
            if idx < 0:
                no_strike += 1
                continue
            level = anchor(strikes[idx][1], strikes[idx][0], tape, row["frozen_at"])
            if level is None:
                no_candle += 1
                continue
            variant = variant_prob(forecaster, row["payload"], interval, level)
            outcome = int(row["outcome"])
            briers["original"].append(_brier(row["probability"], outcome))
            briers["variant"].append(_brier(variant, outcome))
            if row.get("market_prob") is not None:
                briers["market"].append(_brier(row["market_prob"], outcome))
            # Improvement diffs: original minus variant, so positive is better.
            diffs.append((row["frozen_at"].astimezone(_ET).date().isoformat(),
                          _brier(row["probability"], outcome) - _brier(variant, outcome)))
            scored += 1
        total = len(rows)
        mean_diff = sum(d for _day, d in diffs) / len(diffs) if diffs else None
        series_out[forecaster] = {
            "rows_total": total, "rows_scored": scored,
            "excluded_mismatch": mismatch, "excluded_no_strike": no_strike,
            "excluded_no_candle": no_candle,
            "mismatch_flood": bool(total and mismatch / total > FLOOD_SHARE),
            "days": len({day for day, _d in diffs}),
            "brier": {k: (sum(v) / len(v) if v else None) for k, v in briers.items()},
            "improvement_mean": mean_diff,
            "improvement_low95": clustered_low95(diffs) if diffs else None,
        }
    earns = False
    if not any(s["mismatch_flood"] for s in series_out.values()):
        for name, s in series_out.items():
            low, gain = s["improvement_low95"], s["improvement_mean"]
            if low is None or gain is None or low <= 0:
                continue
            others_ok = all(
                (o["improvement_low95"] is None or o["improvement_low95"] >= -gain)
                for k, o in series_out.items() if k != name)
            if others_ok:
                earns = True
    return {"series": series_out,
            "verdict": {"earns_shadow": earns,
                        "rule": "a series' paired Brier improvement (original - variant) must "
                                "have a day-clustered low95 above zero, and no other series "
                                "may be worse by more than that gain (prereg, frozen)"}}
