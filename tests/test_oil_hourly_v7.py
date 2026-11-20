"""Tests for the hourly oil v7 shadow (`oil_wti_hourly`, `wti-hourly-v7-rv-shadow`):
v4's Hyperliquid anchor with the spread from 1-minute realised volatility.

Preregistration: docs/superpowers/specs/2026-11-19-oil-hourly-v7-rv-shadow-prereg.md.
The variant differs from v4 ONLY in the sigma source, which is what makes the
paired grading meaningful; these tests pin that the forecast prices off the RV
sigma (never the settled-changes sigma), that a tape gap is no forecast, and
that the registry carries v7 as a live shadow beside v4.
"""

import statistics
from datetime import UTC, datetime, timedelta

from tradehub.backtest.pit import Observation
from tradehub.data.hyperliquid import HyperliquidUnavailable
from tradehub.engines.oil_hourly import MIN_HOURLY_SIGMA, hourly_prob, realised_sigma
from tradehub.journal.forecasters.oil_hourly import HourlyInputs
from tradehub.journal.forecasters.oil_v7 import OilWtiHourlyRvShadow, build_oil_v7_shadow

from tests.test_journal_oil_hourly import CLOSE, NOW, FakeLive, _lm


def _candles(diffs, start=None):
    """(open time, close) pairs whose consecutive differences are `diffs`."""
    t = start or (NOW - timedelta(minutes=len(diffs) + 1))
    out, price = [(t, 100.0)], 100.0
    for d in diffs:
        t += timedelta(minutes=1)
        price += d
        out.append((t, round(price, 4)))
    return out


def _horizon(entry, now=NOW):
    return max(0, int((entry.cutoff_at - now).total_seconds()))


def _fc(candles, price=101.20, anchor_at=None, live_price=999.0, v4_offset_s=0, v4_horizon="same"):
    # The anchor is v4's frozen observation (Claude's review: the pair
    # must share one anchor). The forecaster's own live read is a
    # different number on purpose -- v7 must never price off it.
    live = FakeLive([_lm(101)])
    anchor = Observation("xyz:CL", price, anchor_at or (NOW - timedelta(minutes=1)))
    own = Observation("xyz:CL", live_price, NOW - timedelta(minutes=1))
    fc = OilWtiHourlyRvShadow(live, lambda ticker: None,
                              HourlyInputs(live, price_fn=lambda: own),
                              candles_fn=lambda now: candles,
                              anchor_fn=lambda target: None)
    entries = fc.targets(NOW)
    assert len(entries) == 1
    h = None if v4_horizon is None else _horizon(entries[0]) + v4_offset_s
    fc._anchor_fn = lambda target: (anchor, h)
    return fc, entries[0]


# ---- the RV sigma -----------------------------------------------------------

def test_realised_sigma_scales_the_1m_stdev_to_an_hour():
    diffs = [0.02, -0.01] * 100                      # 200 usable differences
    out = realised_sigma(_candles(diffs))
    assert out is not None
    sigma_h, used, sigma_1m = out
    assert used == 200
    assert abs(sigma_1m - statistics.stdev(diffs)) < 1e-9
    assert abs(sigma_h - statistics.stdev(diffs) * (60 ** 0.5)) < 1e-9


def test_realised_sigma_breaks_pairs_at_a_missing_minute():
    candles = _candles([0.02] * 150)
    del candles[75]                                  # a 2-minute gap: two pairs die
    out = realised_sigma(candles)
    assert out is not None and out[1] == 148


def test_realised_sigma_floors_a_dead_quiet_tape():
    out = realised_sigma(_candles([0.0] * 200))
    assert out is not None and out[0] == MIN_HOURLY_SIGMA


def test_realised_sigma_refuses_a_thin_tape():
    assert realised_sigma(_candles([0.02] * 119)) is None
    assert realised_sigma([]) is None


# ---- the forecaster ----------------------------------------------------------

def test_forecast_prices_off_the_rv_sigma_not_the_settled_sigma():
    # A quiet 1-minute tape (RV sigma ~0.12/h) against settled changes whose
    # hourly sigma is ~0.11 either way; the point is which number lands in the
    # payload and the probability: the RV one, recomputed independently here.
    diffs = [0.01, -0.01] * 100
    candles = _candles(diffs)
    fc, entry = _fc(candles)
    row = fc.forecast(entry, NOW)
    assert row is not None
    sigma_h, _used, _s1 = realised_sigma(candles)
    minutes = (CLOSE - NOW).total_seconds() / 60.0
    assert row.probability == hourly_prob(_lm(101).market, 101.20, sigma_h, minutes)
    assert row.forecaster_version == "wti-hourly-v7-rv-shadow"
    assert row.payload["sigma_source"] == "rv_1m_24h"
    assert row.payload["rv_diffs_used"] == 200
    assert row.payload["sigma_h"] == sigma_h
    # The anchor in the payload is v4's frozen observation, not the
    # forecaster's own live read (999.0 in this harness).
    assert row.payload["live_price"] == 101.20
    assert row.payload["anchor_source"] == "v4_frozen"
    assert "changes_used" not in row.payload


def test_forecast_is_a_gap_when_the_tape_is_dead_or_thin():
    def boom(now):
        raise HyperliquidUnavailable("down")

    live = FakeLive([_lm(101)])
    anchor = Observation("xyz:CL", 101.20, NOW - timedelta(minutes=1))
    fc = OilWtiHourlyRvShadow(live, lambda ticker: None,
                              HourlyInputs(live, price_fn=lambda: anchor),
                              candles_fn=boom,
                              anchor_fn=lambda target: None)
    entries = fc.targets(NOW)
    fc._anchor_fn = lambda target: (anchor, _horizon(entries[0]))
    assert fc.forecast(entries[0], NOW) is None

    fc2, entry2 = _fc(_candles([0.02] * 60))         # 60 diffs < the 120 floor
    assert fc2.forecast(entry2, NOW) is None


def test_no_v4_row_no_forecast():
    # No frozen v4 anchor for the target: no pair, so no v7 row.
    live = FakeLive([_lm(101)])
    obs = Observation("xyz:CL", 101.20, NOW - timedelta(minutes=1))
    fc = OilWtiHourlyRvShadow(live, lambda ticker: None,
                              HourlyInputs(live, price_fn=lambda: obs),
                              candles_fn=lambda now: _candles([0.01] * 200),
                              anchor_fn=lambda target: None)
    entries = fc.targets(NOW)
    assert fc.forecast(entries[0], NOW) is None


def test_a_stale_v4_anchor_is_a_gap():
    fc, entry = _fc(_candles([0.01] * 200),
                    anchor_at=NOW - timedelta(minutes=16))  # past MAX_PRICE_AGE
    assert fc.forecast(entry, NOW) is None


def test_the_candle_read_drops_the_in_progress_minute(monkeypatch):
    from tradehub.journal.forecasters import oil_v7

    raw = _candles([0.01] * 10, start=NOW - timedelta(minutes=11))
    raw.append((NOW - timedelta(seconds=30), 555.0))  # the in-progress minute
    monkeypatch.setattr(oil_v7, "hyperliquid_candles", lambda *a, **k: raw)
    got = oil_v7._hl_candles_or_none(NOW)
    assert got is not None
    assert all(v != 555.0 for _t, v in got)
    assert got[-1][0] + timedelta(minutes=1) <= NOW


def test_registry_carries_v7_live_beside_v4():
    from tradehub.journal.registry import FORECASTERS, RETIRED

    pairs = {(f.name, f.version) for f in FORECASTERS}
    retired = {(f.name, f.version) for f in RETIRED}
    assert ("oil_wti_hourly", "wti-hourly-v7-rv-shadow") in pairs
    assert ("oil_wti_hourly", "wti-hourly-v4-hl-shadow") in pairs
    assert ("oil_wti_hourly", "wti-hourly-v7-rv-shadow") not in retired
    built = build_oil_v7_shadow(FakeLive([]))
    assert [f.version for f in built] == ["wti-hourly-v7-rv-shadow"]



def test_v7_pairs_only_with_a_v4_row_frozen_on_the_same_pass():
    # CodeRabbit on #564: v7 could freeze on a later pass than v4, so the pair
    # would mix decision times (minutes-to-close, RV window, horizon).
    candles = _candles([0.01] * 200)
    fc, entry = _fc(candles)                            # same pass: same `now`, same horizon
    out = fc.forecast(entry, NOW)
    assert out is not None and out.payload["v4_horizon_seconds"] == _horizon(entry)
    fc, entry = _fc(candles, v4_offset_s=20)            # a retry pass 20 s later (CodeRabbit)
    assert fc.forecast(entry, NOW) is None
    fc, entry = _fc(candles, v4_offset_s=600)           # v4 froze ten minutes earlier
    assert fc.forecast(entry, NOW) is None
    fc, entry = _fc(candles, v4_horizon=None)           # v4 row without a recorded horizon
    assert fc.forecast(entry, NOW) is None
