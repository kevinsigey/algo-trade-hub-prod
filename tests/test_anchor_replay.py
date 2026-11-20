"""Tests for the step-17 anchor replay (daily natgas + Brent re-centred on the
latest Kalshi 15-minute strike). Preregistration:
docs/superpowers/specs/2026-11-19-anchor-replay-prereg.md.

The study's honesty rests on two pins these tests hold: the stored probability
is recomputed from its frozen payload before any variant is scored (a row the
study cannot reproduce is excluded, never re-anchored), and the anchor is the
strike plus the perp's move since that strike's window opened -- nothing else
moves.
"""

import math
from datetime import UTC, datetime, timedelta

from tradehub.markets import prob_in_interval
from tradehub.research.anchor_replay import (
    anchor,
    build_report,
    recompute_original,
    strike_from_target,
    variant_prob,
    yes_interval_greater,
)

FROZEN = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)
OPEN = datetime(2026, 11, 10, 19, 45, tzinfo=UTC)   # the latest 15m window open


def _candles():
    """The stored tape as (instant, price) points, one per minute: 3.300 at
    OPEN, drifting up 0.001 a minute to FROZEN."""
    out, t, price = [], OPEN - timedelta(minutes=30), 3.270
    while t <= FROZEN:
        price += 0.001
        out.append((t, round(price, 4)))
        t += timedelta(minutes=1)
    return out


def _natgas_row(prob=None, outcome=1):
    payload = {"live_price": 3.316, "sigma_eff": 0.0217}
    interval = yes_interval_greater(2.850, 0.001)
    stored = prob_in_interval(3.316, 0.0217, interval) if prob is None else prob
    return {"target": "kalshi:KXNATGASD-26NOV1017-T2.850", "frozen_at": FROZEN,
            "probability": stored, "market_prob": 0.99, "payload": payload,
            "outcome": outcome}


def _brent_row(prob=None, outcome=0):
    payload = {"last_settlement": 91.67, "horizon_days": 1, "cl_change_5": -12.2,
               "alpha": -0.0419, "beta": -0.00059, "sigma": 3.128}
    interval = yes_interval_greater(100.0, 0.01)
    stored = recompute_original("oil_brent", payload, interval) if prob is None else prob
    return {"target": "kalshi:KXBRENTD-26NOV1017-T100", "frozen_at": FROZEN,
            "probability": stored, "market_prob": 0.01, "payload": payload,
            "outcome": outcome}


def test_strike_and_interval_read_the_ticker():
    assert strike_from_target("kalshi:KXNATGASD-26NOV1017-T2.850") == 2.850
    assert strike_from_target("kalshi:KXBRENTD-26NOV1017-T100.50") == 100.50
    lo, hi = yes_interval_greater(2.850, 0.001)
    assert abs(lo - 2.8505) < 1e-12 and hi == math.inf


def test_recompute_reproduces_the_stored_probabilities():
    row = _natgas_row()
    assert abs(recompute_original("natgas_daily", row["payload"],
                                  yes_interval_greater(2.850, 0.001))
               - row["probability"]) < 1e-9
    row = _brent_row()
    assert abs(recompute_original("oil_brent", row["payload"],
                                  yes_interval_greater(100.0, 0.01))
               - row["probability"]) < 1e-9


def test_anchor_is_the_strike_plus_the_perp_move_since_the_open():
    candles = _candles()
    by_instant = dict(candles)
    at_open = by_instant[OPEN]
    at_freeze = by_instant[FROZEN]
    assert abs(anchor(2.850, OPEN, candles, FROZEN) - (2.850 + (at_freeze - at_open))) < 1e-9
    assert anchor(2.850, OPEN, [], FROZEN) is None
    stale = [(OPEN - timedelta(minutes=10), 3.30)]     # nothing within 2 minutes
    assert anchor(2.850, OPEN, stale, FROZEN) is None
    assert variant_prob("natgas_daily", _natgas_row()["payload"],
                        yes_interval_greater(2.850, 0.001), 2.880) == \
        prob_in_interval(2.880, 0.0217, yes_interval_greater(2.850, 0.001))


def test_report_excludes_what_it_cannot_reproduce_or_anchor():
    good = _natgas_row()
    bad = _natgas_row(prob=0.5)                       # stored prob != recomputation
    early = _natgas_row()
    early["frozen_at"] = OPEN - timedelta(hours=2)    # before any strike window
    report = build_report(
        {"natgas_daily": [good, bad, early], "oil_brent": [_brent_row()]},
        {"natgas_daily": [(OPEN, 2.850)], "oil_brent": [(OPEN, 92.0)]},
        {"natgas_daily": _candles(), "oil_brent": _candles()})
    gas = report["series"]["natgas_daily"]
    assert gas["rows_scored"] == 1
    assert gas["excluded_mismatch"] == 1 and gas["excluded_no_strike"] == 1
    assert report["series"]["oil_brent"]["rows_scored"] == 1
    assert set(gas["brier"]) == {"original", "variant", "market"}
    assert "verdict" in report


def test_a_mismatch_flood_reports_no_verdict():
    rows = [_natgas_row(prob=0.5) for _ in range(10)] + [_natgas_row()]
    report = build_report({"natgas_daily": rows, "oil_brent": []},
                          {"natgas_daily": [(OPEN, 2.850)], "oil_brent": []},
                          {"natgas_daily": _candles(), "oil_brent": []})
    assert report["series"]["natgas_daily"]["mismatch_flood"] is True
    assert report["verdict"]["earns_shadow"] is False
