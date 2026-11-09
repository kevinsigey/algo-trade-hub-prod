"""Phase 0 valuation engine tests (spec: valuation-bands Spec v1, sections 1-2).

Pure-function tests: band construction, 10% bear haircut, gap in guide-range
widths, zone classification both directions, staleness refusal, sanity-guard
rejections, direction/percentile math. Failing-first per hub discipline.
"""
from datetime import date, datetime, timezone

import pytest

from tradehub.valuation import engine

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def rec(ticker="ACME", metric="eps_adjusted", period="FY2027", low=4.0, high=5.0,
        unit="usd_per_share", consensus=4.2, created="2026-11-01T00:00:00+00:00",
        consensus_period="FY2027"):
    return {"ticker": ticker, "metric": metric, "period": period, "low": low,
            "high": high, "unit": unit, "consensus": consensus,
            "consensus_period": consensus_period,
            "created_at": created, "accession": "0001"}


def sheet(records, price=80.0, mult=20.0, **kw):
    kw.setdefault("peer_median_fwd_eps", 4.0)
    kw.setdefault("peer_count", 6)
    kw.setdefault("peer_basis", "industry_group")
    kw.setdefault("guided_peers", [])
    kw.setdefault("fundamentals", {})
    kw.setdefault("price_date", date(2026, 11, 7))
    return engine.build_fact_sheet(ticker=records[0]["ticker"], records=records,
                                   price=price, peer_multiple=mult, now=NOW, **kw)


# --- period parsing --------------------------------------------------------

@pytest.mark.parametrize("period,ok", [
    ("FY2027", True), ("full year 2027", True), ("Fiscal 2027", True),
    ("Year ending December 31, 2026", True), ("2027", True),
    ("Q4 2026", False), ("Q3 FY2026", False), ("4Q26", False),
    ("First Quarter 2027", False), ("2030", False), ("", False),
])
def test_full_year_period_parsing(period, ok):
    assert engine.is_full_year_period(period) is ok


# --- band construction + haircut -------------------------------------------

def test_bands_from_guide_with_bear_haircut():
    s = sheet([rec()])
    # guide 4.00-5.00, multiple 20 -> bull 100, base 90, bear 4.0*0.9*20 = 72
    assert s["status"] == "banded"
    assert s["bands"] == {"bear": 72.0, "base": 90.0, "bull": 100.0}
    assert s["anchor"]["metric"] == "eps_adjusted"
    assert s["anchor"]["mid"] == 4.5


def test_gaap_fallback_when_no_adjusted():
    s = sheet([rec(metric="eps_gaap")])
    assert s["status"] == "banded"
    assert s["anchor"]["metric"] == "eps_gaap"


def test_adjusted_preferred_over_gaap():
    s = sheet([rec(metric="eps_gaap", low=3.0, high=3.5),
               rec(metric="eps_adjusted", low=4.0, high=5.0)])
    assert s["anchor"]["metric"] == "eps_adjusted"


def test_latest_record_wins_within_same_period():
    older = rec(low=3.0, high=3.4, created="2026-08-01T00:00:00+00:00")
    newer = rec(low=4.0, high=5.0, created="2026-11-01T00:00:00+00:00")
    s = sheet([older, newer])
    assert s["anchor"]["low"] == 4.0


# --- gap in range widths ----------------------------------------------------

def test_gap_in_range_widths():
    # price 80 / multiple 20 -> implied EPS 4.0; mid 4.5; width 1.0 -> gap -0.5
    s = sheet([rec()], price=80.0)
    assert s["gap_range_widths"] == pytest.approx(-0.5)
    assert s["implied"]["eps"] == pytest.approx(4.0)


def test_point_guide_gap_is_null():
    s = sheet([rec(low=4.5, high=4.5)], price=80.0)
    assert s["status"] == "banded"
    assert s["gap_range_widths"] is None
    assert s["anchor"]["point_guide"] is True


# --- zone classification, both directions -----------------------------------

@pytest.mark.parametrize("price,zone", [
    (70.0, "buy_zone_strong"),   # <= bear 72
    (80.0, "buy_zone"),          # <= base 90
    (95.0, "neutral"),           # <= bull 100, implied 4.75 > mid 4.5? no: 4.75>4.5 -> short side
])
def test_zones_long_side(price, zone):
    s = sheet([rec()], price=price)
    assert s["baseline_verdict"] == zone


def test_zone_neutral_when_implied_inside_guide():
    # price 92 -> implied 4.6, inside guide [4.0, 5.0]; base 90 < price <= bull 100
    s = sheet([rec()], price=92.0)
    assert s["baseline_verdict"] == "neutral"


def test_zone_short_strong_above_bull_with_rich_implied():
    s = sheet([rec()], price=120.0)  # implied 6.0 > high 5.0
    assert s["baseline_verdict"] == "short_zone_strong"


def test_zone_no_chase_above_bull_but_implied_cheap():
    # Wide guide so implied stays inside even above bull is impossible (bull =
    # high x M); use a cut guide: latest guide low but price still above bull
    # while implied < mid cannot happen either; instead verify the documented
    # branch via a peer multiple change: price 101, mult 25 -> implied 4.04,
    # bull = 5*25 = 125 so not above bull. Direct unit check of classify:
    z = engine.classify_zone(price=130.0, bands={"bear": 72.0, "base": 90.0,
                                                 "bull": 100.0},
                             implied_eps=4.2, guide_low=4.0, guide_high=5.0,
                             guide_mid=4.5)
    assert z == "no_chase_long"


# --- sanity guards ------------------------------------------------------------

def test_guard_rejects_zero_revenue_style_eps():
    # KO-shaped noise: EPS guide 9.0 vs consensus 3.34 -> ratio 2.69 > 2.5
    s = sheet([rec(low=9.0, high=None, consensus=3.34)])
    assert s["status"] != "banded"
    assert any("consensus" in r for r in s["guard_rejections"])


def test_guard_rejects_nonpositive_low():
    s = sheet([rec(low=0.0, high=1.0)])
    assert s["status"] != "banded"


def test_guard_rejects_wrong_unit():
    s = sheet([rec(unit="usd_millions")])
    assert s["status"] != "banded"


def test_guard_rejects_guide_far_from_trailing_eps():
    s = sheet([rec(low=40.0, high=44.0, consensus=None)],
              fundamentals={"eps_diluted": {"value": 5.0,
                                            "as_of": "2025-12-31"}})
    assert s["status"] != "banded"
    assert any("trailing" in r for r in s["guard_rejections"])


def test_quarterly_only_eps_no_bands():
    s = sheet([rec(period="Q4 2026")])
    assert s["status"] == "no_full_year_guide"
    assert s["bands"] is None


def test_revenue_only_no_bands_but_direction_tracked():
    rows = [rec(metric="revenue", unit="usd_billions", low=30.7, high=31.0,
                consensus=31.2, created="2026-11-05T00:00:00+00:00"),
            rec(metric="revenue", unit="usd_billions", low=31.0, high=31.3,
                consensus=31.2, created="2026-08-05T00:00:00+00:00")]
    s = sheet(rows)
    assert s["status"] == "no_full_year_guide"
    assert s["directions"]["revenue"]["direction"] == "cut"


# --- direction ----------------------------------------------------------------

def test_direction_raised_held_cut():
    base = [rec(created="2026-08-01T00:00:00+00:00")]
    raised = base + [rec(low=4.4, high=5.4, created="2026-11-01T00:00:00+00:00")]
    assert sheet(raised)["directions"]["eps_adjusted"]["direction"] == "raised"
    held = base + [rec(low=4.01, high=5.0, created="2026-11-01T00:00:00+00:00")]
    assert sheet(held)["directions"]["eps_adjusted"]["direction"] == "held"
    assert sheet(base)["directions"]["eps_adjusted"]["direction"] == "first"


# --- staleness ------------------------------------------------------------------

def test_stale_price_suppresses_zone():
    s = sheet([rec()], price_date=date(2026, 10, 1))
    assert s["stale"] is True
    assert s["baseline_verdict"] == "stale"


def test_stale_guide_suppresses_zone():
    s = sheet([rec(created="2026-03-01T00:00:00+00:00")])
    assert s["stale"] is True
    assert s["baseline_verdict"] == "stale"


def test_no_peer_multiple_status():
    s = sheet([rec()], mult=None)
    assert s["status"] == "no_peer_multiple"
    assert s["bands"] is None


# --- percentile -----------------------------------------------------------------

def test_guidance_relative_percentile():
    peers = [
        {"ticker": "ACME", "surprise": 0.10},
        {"ticker": "BETA", "surprise": -0.05},
        {"ticker": "GAMMA", "surprise": 0.02},
    ]
    s = sheet([rec()], guided_peers=peers)
    # ACME surprise: mid 4.5 vs consensus 4.2 -> +0.0714; ranks top of 3 -> 100th
    assert s["guidance_percentile"] == pytest.approx(100.0)


def test_falsifier_text_present_when_banded():
    s = sheet([rec()])
    assert "FY2027" in s["falsifier"]
    assert "4.00" in s["falsifier"]
