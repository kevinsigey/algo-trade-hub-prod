"""Deeper look at a run: year by year, rolling 12-month excess, raw daily data (Kevin, 2026-10-31)."""
import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.engine import analysis


def frame(days=600, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=days)
    return pd.DataFrame({"ret": rng.normal(0.0005, 0.01, days), "on": rng.random(days) < 0.4,
                         "bench": rng.normal(0.0004, 0.01, days), "spy": rng.normal(0.0004, 0.01, days),
                         "exit": ""}, index=idx)


def test_years_compound_each_calendar_year():
    f = frame()
    out = analysis(f)
    y2020 = next(y for y in out["years"] if y["year"] == 2020)
    part = f[f.index.year == 2020]
    assert y2020["idea"] == pytest.approx(((1 + part.ret).prod() - 1) * 100)
    assert y2020["bench"] == pytest.approx(((1 + part.bench).prod() - 1) * 100)
    assert y2020["excess"] == pytest.approx(y2020["idea"] - y2020["bench"])
    assert y2020["days_in"] == pytest.approx(part.on.mean() * 100)
    assert y2020["idea_in"] == pytest.approx(((1 + part.ret[part.on]).prod() - 1) * 100)
    assert [y["year"] for y in out["years"]] == [2020, 2021, 2022]


def test_rolling_12_month_excess():
    f = frame()
    out = analysis(f)
    last = out["rolling"][-1]
    tail = f.iloc[-252:]
    want = ((1 + tail.ret).prod() - (1 + tail.bench).prod()) * 100
    assert last["t"] == str(f.index[-1].date()) and last["excess"] == pytest.approx(want)
    assert out["rolling"][0]["t"] == str(f.index[251].date())  # first full 12 months


def test_a_year_never_in_has_no_return_while_in():
    f = frame(300)
    f.loc[f.index.year == 2021, "on"] = False
    assert next(y for y in analysis(f)["years"] if y["year"] == 2021)["idea_in"] is None


def test_short_history_has_no_rolling():
    assert analysis(frame(100))["rolling"] == []


def test_days_in_counts_held_days_not_rule_days():
    # Review: after a stop the rule can still be on while the idea is out; "days in" means held.
    f = frame(260)
    f["on"] = True
    f["held"] = f.index.month <= 6
    y = analysis(f)["years"][0]
    part = f[f.index.year == 2020]
    assert y["days_in"] == pytest.approx(part.held.mean() * 100)
    assert y["idea_in"] == pytest.approx(((1 + part.ret[part.held]).prod() - 1) * 100)


def test_daily_frame_has_the_held_position():
    from tradehub.workshop.engine import daily_frame
    from tradehub.workshop.spec import IdeaSpec
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2015-01-02", periods=900)
    closes = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0, 0.02, len(idx))) for t in ("SPY", "QQQ", "IWM", "AAA")},
                          index=idx)
    s = IdeaSpec(title="AAA with a stop", hold=["AAA"], claim="beats_benchmark", start="2015-01-02",
                 exits={"stop_loss_pct": 3})
    df = daily_frame(s, closes, {})
    assert df["on"].all() and not df["held"].all() and (df["held"] <= df["on"]).all()
