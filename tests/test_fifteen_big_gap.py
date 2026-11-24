"""oil-big-gap-v1 (docs/superpowers/specs/2026-11-24-oil-big-gap-v1-prereg.md):
keeps raw-rule buys whose side gap is 15+ points, never registers gas or
metals, and shares the trend shadow's machinery without changing it."""

from datetime import UTC, datetime

from tradehub import fifteen_candidates as fc

PREREG = datetime(2026, 11, 25, tzinfo=UTC)


def test_gap_boundary_both_sides():
    assert fc.gap_skip_reason("yes", 0.65, 0.50) is None          # 0.15 kept
    assert fc.gap_skip_reason("yes", 0.70, 0.55) is None          # float-noisy 0.15 kept
    assert fc.gap_skip_reason("yes", 0.6499, 0.50) == "gap_below_15"
    assert fc.gap_skip_reason("no", 0.35, 0.50) is None           # 1 - 0.35 - 0.50 = 0.15
    assert fc.gap_skip_reason("no", 0.3501, 0.50) == "gap_below_15"


def _fc(target, frozen_at, p, ask, bid):
    return {"target": target, "frozen_at": frozen_at, "probability": p,
            "payload": {"yes_ask": ask, "yes_bid": bid, "price": 70.0}}


def test_decisions_use_the_frozen_cost():
    rows = [_fc("y_keep", "2026-11-25T15:05:00+00:00", 0.65, 0.50, 0.48),
            _fc("y_drop", "2026-11-25T15:20:00+00:00", 0.6499, 0.50, 0.48),
            _fc("n_keep", "2026-11-25T15:35:00+00:00", 0.35, 0.52, 0.50),   # NO costs 1 - bid
            _fc("n_drop", "2026-11-25T15:50:00+00:00", 0.3501, 0.52, 0.50)]
    ds = {d["target"]: d for d in fc.raw_decisions(fc.BIG_GAP, rows, {}, fc.BRENT, PREREG)}
    assert {t: (d["side"], d["action"]) for t, d in ds.items()} == {
        "y_keep": ("yes", "buy"), "y_drop": ("yes", "skip"),
        "n_keep": ("no", "buy"), "n_drop": ("no", "skip")}
    assert ds["y_drop"]["reason"] == "gap_below_15"
    for series in (fc.NATGAS, fc.GOLD, fc.SILVER, fc.COPPER):
        assert fc.raw_decisions(fc.BIG_GAP, rows, {}, series, PREREG) == []


def test_registered_beside_trend_and_off_the_demo_lane():
    assert [s.version for s in fc.RAW_SHADOWS] == ["oil-trend-agree-v1", "oil-big-gap-v1"]
    assert fc.BIG_GAP.prereg_at == datetime(2026, 11, 24, 21, 0, tzinfo=UTC)
    assert fc.TREND.prereg_at == datetime(2026, 11, 24, 18, 0, tzinfo=UTC)
    assert fc.BIG_GAP.version not in fc.CANDIDATES
    assert fc.raw_evaluate(fc.BIG_GAP, [], now=PREREG)["version"] == "oil-big-gap-v1"
