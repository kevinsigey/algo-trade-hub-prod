from datetime import date

from tradehub.workshop.record import FAILING_WINDOW, shadow_summary
from tradehub.workshop.spec import IdeaSpec

SPEC = IdeaSpec(title="AAA beats SPY", hold=["AAA"], claim="beats_benchmark")


def rows(n, edge, start_day=1):
    days = [date.fromordinal(date(2026, 11, 2).toordinal() + k) for k in range(n)]
    return [{"day": str(d), "ret": 0.001 + edge, "on": True, "bench": 0.001, "spy": 0.001} for d in days]


def test_empty_track():
    out = shadow_summary(SPEC, [], today=date(2026, 11, 3))
    assert out["days"] == 0 and out["failing"] is False and out["curve"] == [] and out["state"] == "waiting"


def test_returns_and_curve():
    out = shadow_summary(SPEC, rows(3, 0.0), today=date(2026, 11, 5))
    assert out["return_pct"] == out["bench_return_pct"] and round(out["return_pct"], 3) == 0.3
    assert out["as_of"] == "2026-11-04" and out["state"] == "live" and len(out["curve"]) == 3


def test_failing_needs_a_full_window():
    early = shadow_summary(SPEC, rows(FAILING_WINDOW - 1, -0.002), today=date(2027, 3, 1))
    assert early["failing"] is False and FAILING_WINDOW == 63
    full = shadow_summary(SPEC, rows(80, 0.002)[:17] + rows(80, -0.002)[17:], today=date(2027, 3, 1))
    assert full["failing"] is True and full["claim"]["days"] == 63


def test_stale_after_three_weekdays():
    out = shadow_summary(SPEC, rows(1, 0.0), today=date(2026, 11, 9))  # last day Mon 11-02, today Mon 11-09
    assert out["state"] == "stale"
