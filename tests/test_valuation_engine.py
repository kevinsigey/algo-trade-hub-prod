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


@pytest.mark.parametrize("period,ok", [
    # Amendment A2 (2026-11-09): the frozen method names calendar-year phrasing and
    # the hyphenated full-year; the matcher is aligned to it.
    ("full-year 2026", True), ("Full-Year 2027", True),
    ("Calendar 2026", True), ("calendar year 2026", True),
    # Standing exclusions are unchanged: out-of-window years and quarter tokens.
    ("full-year 2030", False), ("Calendar 2030", False),
    ("Q4 calendar 2026", False), ("Calendar Q1 2026", False),
    ("Second-quarter full-year review 2026", False),
])
def test_full_year_period_phrasings_amended(period, ok):
    assert engine.is_full_year_period(period, now=NOW) is ok


def test_hyphenated_full_year_period_anchors():
    s = sheet([rec(period="full-year 2026")])
    assert s["status"] == "banded"
    assert s["anchor"]["period_key"] == "FY2026"


def test_calendar_year_period_anchors():
    s = sheet([rec(period="Calendar 2026", metric="eps_gaap", consensus=None)])
    assert s["status"] == "banded"
    assert s["anchor"]["period_key"] == "FY2026"


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


def test_guard_excuses_trailing_when_consensus_corroborates():
    # Amendment A3 (2026-11-09), ABBV shape: adjusted guide 13.95-13.99 matched by its
    # own-basis consensus 13.98, while GAAP trailing EPS (~1.02) is structurally crushed
    # by charges. The GAAP series is not evidence about the adjusted guide -> banded.
    s = sheet([rec(low=13.95, high=13.99, consensus=13.9831,
                   consensus_period="0y")],
              fundamentals={"eps_diluted": {"value": 1.02,
                                            "as_of": "2026-09-30"}})
    assert s["status"] == "banded"
    assert not any("trailing" in r for r in s["guard_rejections"])


def test_guard_excuses_trailing_for_point_guide_cvs_shape():
    # CVS shape: point guide 8.2, consensus 8.218, GAAP trailing 1.39 (ratio 5.9x).
    s = sheet([rec(low=8.2, high=None, consensus=8.21802, consensus_period="0y")],
              fundamentals={"eps_diluted": {"value": 1.39,
                                            "as_of": "2026-09-30"}})
    assert s["status"] == "banded"


def test_guard_still_rejects_when_both_references_fail():
    # The KO pin, with a trailing reference present too: 9.0 vs consensus 3.34 (2.69x)
    # fails its own-basis band, and 9.0 vs trailing 2.97 (3.03x) fails the other --
    # no corroboration, no excuse, still rejected.
    s = sheet([rec(low=9.0, high=None, consensus=3.34)],
              fundamentals={"eps_diluted": {"value": 2.97,
                                            "as_of": "2026-09-30"}})
    assert s["status"] != "banded"
    assert any("consensus" in r for r in s["guard_rejections"])
    assert any("trailing" in r for r in s["guard_rejections"])


def test_guard_trailing_alone_still_governs_without_consensus():
    # No consensus on record -> no excuse available: a guide far below the trailing
    # floor stays rejected (MRK's captured GAAP-only point shape, 2.04 vs ~7.3).
    s = sheet([rec(metric="eps_gaap", low=2.04, high=2.04, consensus=None)],
              fundamentals={"eps_diluted": {"value": 7.3,
                                            "as_of": "2026-09-30"}})
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


# --- revenue basis (Phase B amendment, 2026-11-09) -----------------------------

def rev_rec(ticker="ACME", period="FY2027", low=90e9, high=110e9, unit="usd",
            consensus=98e9, created="2026-11-01T00:00:00+00:00",
            consensus_period="0y"):
    return {"ticker": ticker, "metric": "revenue", "period": period,
            "low": low, "high": high, "unit": unit, "consensus": consensus,
            "consensus_period": consensus_period,
            "created_at": created, "accession": "0002"}


REV_FUND = {"shares_diluted": {"value": 10e9, "as_of": "2026-09-30"},
            "revenue": {"value": 95e9, "as_of": "2026-09-30"}}


def rev_sheet(records, price=50.0, sales=5.0, **kw):
    kw.setdefault("fundamentals", REV_FUND)
    return sheet(records, price=price, sales_multiple=sales, sales_count=6, **kw)


def test_revenue_bands_from_fy_revenue_guide():
    # guide 90-110B, peer P/S 5.0, 10B diluted shares -> bear 40.5, base 50, bull 55
    s = rev_sheet([rev_rec()])
    assert s["status"] == "banded"
    assert s["band_basis"] == "revenue"
    assert s["bands"] == {"bear": 40.5, "base": 50.0, "bull": 55.0}
    assert s["anchor"]["metric"] == "revenue"
    # price 50 -> implied revenue 50 * 10e9 / 5 = 100B = the guide mid -> gap 0
    assert s["implied"]["revenue"] == pytest.approx(100e9)
    assert s["gap_range_widths"] == pytest.approx(0.0)
    assert s["baseline_verdict"] == "buy_zone"


def test_revenue_zone_short_side_mirrors_eps():
    s = rev_sheet([rev_rec()], price=60.0)  # implied 120B > guide high; price > bull
    assert s["baseline_verdict"] == "short_zone_strong"


def test_revenue_point_guide_gap_is_null():
    s = rev_sheet([rev_rec(low=100e9, high=100e9)])
    assert s["status"] == "banded"
    assert s["gap_range_widths"] is None
    assert s["anchor"]["point_guide"] is True
    assert s["bands"] == {"bear": 45.0, "base": 50.0, "bull": 50.0}


def test_eps_basis_wins_when_both_bases_exist():
    s = rev_sheet([rec(), rev_rec()])
    assert s["status"] == "banded"
    assert s["band_basis"] == "eps"
    assert s["anchor"]["metric"] == "eps_adjusted"


def test_revenue_anchor_picks_consolidated_over_segment_rows():
    # ADBE shape: one filing cohort carries segment rows beside the total; the
    # segments pass the magnitude guards (0.69x consensus) but a part never
    # exceeds the whole -- the largest guard-passing midpoint is consolidated.
    seg = rev_rec(low=18.2e9, high=18.3e9, consensus=26.6e9)
    total = rev_rec(low=26.5e9, high=26.6e9, consensus=26.6e9)
    s = rev_sheet([seg, total], fundamentals={
        "shares_diluted": {"value": 0.43e9, "as_of": "2026-09-30"},
        "revenue": {"value": 24e9, "as_of": "2026-09-30"}})
    assert s["status"] == "banded"
    assert s["anchor"]["low"] == 26.5e9


def test_revenue_anchor_prefers_the_latest_cohort():
    older = rev_rec(low=90e9, high=100e9, created="2026-08-01T00:00:00+00:00")
    newer = rev_rec(low=100e9, high=110e9, created="2026-11-01T00:00:00+00:00")
    s = rev_sheet([older, newer])
    assert s["anchor"]["low"] == 100e9


def test_revenue_midpoint_tie_goes_to_the_widest_range():
    point = rev_rec(low=14.65e9, high=14.65e9, consensus=14.7e9)
    rng = rev_rec(low=14.45e9, high=14.85e9, consensus=14.7e9)
    s = rev_sheet([point, rng])
    assert s["anchor"]["low"] == 14.45e9 and s["anchor"]["high"] == 14.85e9


def test_revenue_zero_row_rejected():
    # BKNG shape: a 0.0/0.0 row is not a guide.
    s = rev_sheet([rev_rec(low=0.0, high=0.0, consensus=28.6e9)])
    assert s["status"] == "guide_rejected"
    assert s["bands"] is None


def test_revenue_segment_noise_fails_both_references():
    # KO shape: a 5B row against 50.4B consensus and ~47B trailing revenue.
    s = rev_sheet([rev_rec(low=5e9, high=None, consensus=50.4e9)],
                  fundamentals={"shares_diluted": {"value": 4.3e9,
                                                   "as_of": "2026-09-30"},
                                "revenue": {"value": 47e9,
                                            "as_of": "2026-09-30"}})
    assert s["status"] == "guide_rejected"


def test_revenue_stale_trailing_reference_is_no_reference():
    # PFE shape: the served trailing revenue is FY2023 (as-of > 550 days old at
    # compute). It cannot judge the guide; the consensus reference governs and
    # corroborates -> banded.
    stale = {"shares_diluted": {"value": 5.6e9, "as_of": "2026-09-30"},
             "revenue": {"value": 50.9e9, "as_of": "2023-12-31"}}
    s = rev_sheet([rev_rec(low=62e9, high=64e9, consensus=63e9)],
                  fundamentals=stale)
    assert s["status"] == "banded"
    # ...but a guide its live reference rejects still fails: consensus 30B vs
    # a 62-64B guide is 2.1x -- inside the wide band, so use 20B (3.15x, fails).
    s2 = rev_sheet([rev_rec(low=62e9, high=64e9, consensus=20e9)],
                   fundamentals=stale)
    assert s2["status"] == "guide_rejected"


def test_revenue_no_sales_multiple_status():
    s = rev_sheet([rev_rec()], sales=None)
    assert s["status"] == "no_peer_multiple"
    assert s["bands"] is None


def test_revenue_no_shares_cannot_form_per_share_bands():
    s = rev_sheet([rev_rec()], fundamentals={
        "revenue": {"value": 95e9, "as_of": "2026-09-30"}})
    assert s["status"] == "no_peer_multiple"
    assert s["bands"] is None
    assert "shares" in s["falsifier"]


def test_revenue_quarterly_only_no_bands():
    s = rev_sheet([rev_rec(period="Q4 2026")])
    assert s["status"] == "no_full_year_guide"
    assert s["bands"] is None


def test_fy_two_digit_glued_year_form():
    # A2 completed (Phase B annex): the FY signal always accepted "FY27";
    # the year extractor must read the glued two-digit form too. Quarter
    # forms stay vetoed and out-of-window years stay rejected.
    assert engine.is_full_year_period("FY27", now=NOW) is True
    assert engine.is_full_year_period("Q1 FY27", now=NOW) is False
    assert engine.is_full_year_period("FY30", now=NOW) is False
    assert engine.period_key("FY27") == "FY2027"


def test_revenue_anchor_reads_compact_fy27_period():
    # CRM shape: the FY27 revenue guide bands on the revenue basis.
    s = rev_sheet([rev_rec(period="FY27")])
    assert s["status"] == "banded"
    assert s["band_basis"] == "revenue"
    assert s["anchor"]["period_key"] == "FY2027"


def test_eps_anchor_reads_compact_fy27_period():
    s = sheet([rec(period="FY27")])
    assert s["status"] == "banded"


def test_revenue_pct_growth_row_is_not_a_candidate():
    # ABT shape: a growth-rate row (unit pct) is a different statement, not a
    # rejected dollar guide.
    s = rev_sheet([rev_rec(unit="pct", low=6.5, high=7.5, consensus=None)])
    assert s["status"] == "no_full_year_guide"


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
