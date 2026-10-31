"""Step 6 Part B: analyst rating changes and price targets as rule signals."""
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from tradehub.workshop import signals
from tradehub.workshop.data import UnknownSymbol, analyst
from tradehub.workshop.engine import condition_mask, daily_frame
from tradehub.workshop.spec import IdeaSpec

IDX = pd.bdate_range("2020-01-06", periods=300)


def yf_frame(rows):
    """yfinance's upgrades_downgrades shape: intraday GradeDate index, newest first."""
    df = pd.DataFrame([{"Firm": "X", "ToGrade": "Buy", "FromGrade": "Hold", "Action": a,
                        "priceTargetAction": "Raises", "currentPriceTarget": t, "priorPriceTarget": 0.0}
                       for _, a, t in rows],
                      index=pd.DatetimeIndex([pd.Timestamp(d) for d, _, _ in rows], name="GradeDate"))
    return df.iloc[::-1]


def actions(rows):
    return analyst("AAA", fetch=lambda t: yf_frame(rows), now=datetime(2021, 6, 1, 22, tzinfo=UTC))


def test_net_upgrades_window():
    a = actions([("2020-01-07 13:00", "up", 0), ("2020-01-08 09:00", "up", 0), ("2020-01-10 15:00", "down", 0),
                 ("2020-01-11 10:00", "up", 0)])  # Saturday: counts on Monday the 13th
    out = signals.analyst_measure(a, IDX, "net_upgrades", 3)
    assert out.iloc[0] != out.iloc[0]  # NaN before the first action
    assert out.loc["2020-01-07"] == 1 and out.loc["2020-01-09"] == 2  # 7th-9th: two ups
    assert out.loc["2020-01-10"] == 0  # 8th-10th: up on the 8th, down on the 10th
    assert out.loc["2020-01-13"] == 0 and out.loc["2020-01-20"] == 0  # 9..13 = down+up; later, no actions in window


def test_target_upside_known():
    a = actions([("2020-01-07 13:00", "main", 120.0), ("2020-01-08 13:00", "up", 140.0), ("2020-01-09 13:00", "init", 0.0)])
    close = pd.Series(100.0, index=IDX)
    out = signals.analyst_measure(a, IDX, "target_upside", 5, close=close)
    assert out.loc["2020-01-08"] == pytest.approx(30.0)  # mean(120, 140) / 100 - 1; a 0 target doesn't count
    assert out.loc["2020-01-09"] == pytest.approx(30.0)
    assert np.isnan(out.loc["2020-01-30"])  # no target in the window


def _spec(measure="net_upgrades", n=5, op=">", threshold=0, hold="AAA"):
    c = {"source": "analyst", "series": "AAA", "measure": measure, "lookback_days": n, "op": op, "threshold": threshold}
    return IdeaSpec(title="AAA on upgrades", hold=[hold], claim="beats_benchmark", start="2020-01-06",
                    rules={"enter": {"conditions": [c]}})


def market():
    rng = np.random.default_rng(0)
    return pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(IDX))) for t in ("SPY", "QQQ", "IWM", "AAA")},
                        index=IDX)


def test_analyst_lag_two_days():
    a = actions([("2020-02-03 10:00", "up", 0)])
    mask = condition_mask(_spec(), market(), {"AAA@analyst": a})
    first = mask[mask].index[0]
    assert first == IDX[IDX.get_loc(pd.Timestamp("2020-02-03")) + 2]


def test_analyst_etf_unknown():
    for empty in (pd.DataFrame(), None):
        with pytest.raises(UnknownSymbol, match="no analyst data for XLE"):
            analyst("XLE", fetch=lambda t, e=empty: e)

    def http404(t):
        raise RuntimeError("HTTP Error 404: No fundamentals data found for symbol: XLE")
    with pytest.raises(UnknownSymbol, match="ETFs"):
        analyst("XLE", fetch=http404)


def test_frame_starts_at_analyst_coverage():
    a = actions([("2020-06-01 10:00", "up", 0), ("2020-06-15 10:00", "down", 0)])
    df = daily_frame(_spec(), market(), {"AAA@analyst": a})
    assert df.index[0] > pd.Timestamp("2020-06-01") and df.index[0] <= pd.Timestamp("2020-06-03")


def test_analyst_cache_refresh(tmp_path):
    calls = []

    def fetch(t):
        calls.append(t)
        return yf_frame([("2020-01-07 13:00", "up", 0)])
    evening = datetime(2021, 6, 1, 22, tzinfo=UTC)
    analyst("AAA", fetch=fetch, cache_dir=tmp_path, now=evening)
    got = analyst("AAA", fetch=fetch, cache_dir=tmp_path, now=evening)
    assert calls == ["AAA"] and (tmp_path / "AAA.analyst.csv").exists() and list(got["action"]) == ["up"]
    analyst("AAA", fetch=fetch, cache_dir=tmp_path, now=datetime(2021, 6, 2, 22, tzinfo=UTC))
    assert calls == ["AAA", "AAA"]  # a new complete day refreshes it


def test_actions_after_the_last_complete_day_are_dropped():
    a = analyst("AAA", fetch=lambda t: yf_frame([("2021-06-01 10:00", "up", 0), ("2021-06-02 10:00", "down", 0)]),
                now=datetime(2021, 6, 2, 15, tzinfo=UTC))  # 11:00 New York on the 2nd: the 2nd isn't complete
    assert list(a["action"]) == ["up"] and a.index[0].date() == date(2021, 6, 1)


def test_coverage_starts_after_the_last_long_gap():
    # Review: AAPL has one 2012 row, then nothing until 2019; those empty years must not count as "out" days.
    idx = pd.bdate_range("2012-01-02", "2020-12-31")
    rng = np.random.default_rng(1)
    closes = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0, 0.01, len(idx))) for t in ("SPY", "QQQ", "IWM", "AAA")},
                          index=idx)
    a = actions([("2012-09-12 11:00", "main", 0), ("2019-03-04 10:00", "up", 0), ("2019-06-03 10:00", "down", 0)])
    s = IdeaSpec(title="AAA on upgrades", hold=["AAA"], claim="beats_benchmark", start="2012-01-03",
                 rules={"enter": {"conditions": [{"source": "analyst", "series": "AAA", "measure": "net_upgrades",
                                                  "lookback_days": 63, "op": ">", "threshold": 0}]}})
    assert daily_frame(s, closes, {"AAA@analyst": a}).index[0] >= pd.Timestamp("2019-03-04")


def test_a_failed_fetch_uses_the_cached_actions(tmp_path):
    # Review: a Yahoo hiccup (empty frame or an error) must not read as "an ETF" when yesterday's cache exists.
    rows = [("2020-01-07 13:00", "up", 0)]
    analyst("AAA", fetch=lambda t: yf_frame(rows), cache_dir=tmp_path, now=datetime(2021, 6, 1, 22, tzinfo=UTC))
    today = datetime(2021, 6, 2, 22, tzinfo=UTC)
    assert list(analyst("AAA", fetch=lambda t: pd.DataFrame(), cache_dir=tmp_path, now=today)["action"]) == ["up"]

    def boom(t):
        raise RuntimeError("429 Too Many Requests")
    assert list(analyst("AAA", fetch=boom, cache_dir=tmp_path, now=today)["action"]) == ["up"]
    with pytest.raises(UnknownSymbol, match="Yahoo unavailable"):
        analyst("BBB", fetch=boom, cache_dir=tmp_path, now=today)


def test_actions_just_before_the_start_still_count():
    # CodeRabbit/review: a target set 3 trading days before the first test day is inside a 5-day window.
    a = actions([("2020-01-01 13:00", "up", 150.0)])  # Wednesday before IDX starts (Mon 2020-01-06)
    close = pd.Series(100.0, index=IDX)
    up = signals.analyst_measure(a, IDX, "target_upside", 5, close=close)
    net = signals.analyst_measure(a, IDX, "net_upgrades", 5)
    assert up.iloc[0] == pytest.approx(50.0) and net.iloc[0] == 1
    assert np.isnan(up.iloc[3]) and net.iloc[3] == 0  # aged out of the 5-day window


def test_analyst_cache_written_atomically(tmp_path, monkeypatch):
    import os
    replaced = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (replaced.append((str(a), str(b))), real(a, b))[1])
    analyst("AAA", fetch=lambda t: yf_frame([("2020-01-07 13:00", "up", 0)]), cache_dir=tmp_path,
            now=datetime(2021, 6, 1, 22, tzinfo=UTC))
    assert replaced and replaced[0][1].endswith("AAA.analyst.csv") and list(tmp_path.iterdir()) == [tmp_path / "AAA.analyst.csv"]
    analyst("AAA", fetch=lambda t: yf_frame([("2020-01-07 13:00", "up", 0)]), cache_dir=tmp_path,
            now=datetime(2021, 6, 2, 22, tzinfo=UTC))  # a second refresh of the same ticker
    assert len(replaced) == 2 and replaced[0][0] != replaced[1][0]  # each writer gets its own temp file
