"""Event studies in the Workshop (Kevin, 2026-10-31): earnings, FOMC/CPI/jobs days and price gaps, measured the
IB Python Models way (abnormal return vs SPY on the reaction day, then 1-3/1-5/1-10 day drift) and judged on the
newest events it has not seen, against random dates."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradehub.workshop.events import EventSpec, measure, reaction_day, run_event_test, shrink

IDX = pd.bdate_range("2015-01-02", "2026-10-30")


def market(seed=0, drift_after=None, events=()):
    rng = np.random.default_rng(seed)
    spy = rng.normal(0.0003, 0.01, len(IDX))
    aaa = spy + rng.normal(0, 0.012, len(IDX))
    if drift_after is not None:
        for d in events:
            i = IDX.get_loc(d)
            aaa[i + 1:i + 6] += drift_after  # planted drift on days +1..+5
    return pd.DataFrame({"SPY": 100 * np.cumprod(1 + spy), "AAA": 100 * np.cumprod(1 + aaa)}, index=IDX)


def spec(**over):
    base = {"title": "AAA drifts up after earnings beats", "tickers": ["AAA"], "event": "earnings", "when": "beat",
            "window": "drift_1_5", "direction": "up", "start": "2015-01-02"}
    return EventSpec.model_validate({**base, **over})


def test_reaction_day_follows_the_print_time():
    days = pd.bdate_range("2026-10-26", periods=5)
    assert reaction_day(pd.Timestamp("2026-10-27 07:00"), days) == pd.Timestamp("2026-10-27")  # before the open
    assert reaction_day(pd.Timestamp("2026-10-27 16:05"), days) == pd.Timestamp("2026-10-28")  # after the close
    assert reaction_day(pd.Timestamp("2026-10-24 10:00"), days) == pd.Timestamp("2026-10-26")  # a Saturday release
    assert reaction_day(pd.Timestamp("2026-11-30 10:00"), days) is None  # past the data


def test_measure_is_abnormal_return_vs_spy():
    closes = market(1)
    r = closes.pct_change()
    ar = r["AAA"] - r["SPY"]
    d = IDX[100]
    row = measure(pd.DataFrame({"day": [d], "surprise": [5.0]}), r["AAA"], r["SPY"]).iloc[0]
    assert row["ar0"] == pytest.approx(ar.iloc[100] * 100)
    assert row["car_1_5"] == pytest.approx(ar.iloc[101:106].sum() * 100)
    assert row["car_1_3"] == pytest.approx(ar.iloc[101:104].sum() * 100)
    assert row["pre_5"] == pytest.approx(ar.iloc[95:100].sum() * 100)


def test_events_without_a_full_window_are_dropped():
    closes = market(2)
    r = closes.pct_change()
    out = measure(pd.DataFrame({"day": [IDX[-3]], "surprise": [1.0]}), r["AAA"], r["SPY"])
    assert out.empty


def test_shrinkage_pulls_small_samples_toward_the_pooled_mean():
    per = shrink(pd.DataFrame({"ticker": ["A"] * 3 + ["B"] * 40, "x": [9.0, 8.0, 10.0] + list(np.linspace(-1, 1, 40))}), "x")
    a = per.set_index("ticker").loc["A"]
    assert a["n"] == 3 and a["mean"] == pytest.approx(9.0) and abs(a["shrunk"]) < 9.0 and 0 <= a["weight"] <= 1


def _events(closes, every=63):
    return {"AAA": pd.DataFrame({"time": [pd.Timestamp(d) + pd.Timedelta(hours=7) for d in closes.index[30:-30:every]],
                                 "surprise": [3.0] * len(closes.index[30:-30:every])})}


def test_a_planted_drift_passes():
    days = IDX[30:-30:63]
    closes = market(3, drift_after=0.006, events=days)
    out = run_event_test(spec(), closes, _events(closes), variations=1, seed=1, permutations=500)
    assert out["verdict"] == "PASS", out["headline"]
    assert out["claim"]["unseen"]["holds"] and out["shuffle"]["p"] < 0.05 and out["n_events"] == len(days)
    assert out["per_ticker"][0]["ticker"] == "AAA" and len(out["events"]) == len(days)


def test_noise_fails():
    closes = market(4)
    out = run_event_test(spec(), closes, _events(closes), variations=1, seed=1, permutations=500)
    assert out["verdict"] == "FAIL"


def test_misses_are_filtered_out_of_a_beat_claim():
    closes = market(5)
    ev = _events(closes)
    ev["AAA"]["surprise"] = [-1.0] * len(ev["AAA"])
    out = run_event_test(spec(), closes, ev, variations=1, seed=1)
    assert out["verdict"] == "NOT ENOUGH DATA" and "events" in out["reason"]


def test_a_gap_is_found_from_the_prices():
    closes = market(6)
    i = IDX.get_loc(pd.Timestamp("2020-03-02"))
    closes.iloc[i:, closes.columns.get_loc("AAA")] *= 0.9  # a -10% day vs SPY
    s = spec(event="gap", when="down", gap_pct=8, window="drift_1_5", direction="up")
    out = run_event_test(s, closes, {}, variations=1, seed=1)
    assert any(e["date"] == "2020-03-02" for e in out["events"])


def test_spec_rules():
    with pytest.raises(ValueError, match="gap"):
        spec(event="gap", when="down", window="reaction")
    with pytest.raises(ValueError):
        spec(event="earnings", when="down")
    assert spec(event="fomc", when="all", tickers=["SPY", "QQQ"]).event == "fomc"
    assert spec().start == date(2015, 1, 2)


def test_earnings_dates_from_yahoo_shape(tmp_path):
    from datetime import UTC, datetime
    from tradehub.workshop.data import UnknownSymbol, earnings_dates
    idx = pd.DatetimeIndex(["2027-01-29 07:00", "2026-10-30 06:00", "2026-07-31 16:30"]).tz_localize("America/New_York")
    raw = pd.DataFrame({"EPS Estimate": [3.9, 4.0, 3.6], "Reported EPS": [np.nan, 4.2, 3.5],
                        "Surprise(%)": [np.nan, 4.9, -3.0]}, index=idx)
    calls = []
    now = datetime(2026, 10, 31, 22, tzinfo=UTC)
    got = earnings_dates("XOM", fetch=lambda t: (calls.append(t), raw)[1], cache_dir=tmp_path, now=now)
    assert list(got["time"]) == [pd.Timestamp("2026-07-31 16:30"), pd.Timestamp("2026-10-30 06:00")]  # NY wall time
    assert list(got["surprise"]) == [-3.0, 4.9]  # the unreported future print is dropped
    earnings_dates("XOM", fetch=lambda t: (calls.append(t), raw)[1], cache_dir=tmp_path, now=now)
    assert calls == ["XOM"]
    with pytest.raises(UnknownSymbol, match="earnings"):
        earnings_dates("SPY", fetch=lambda t: None)


def test_release_dates_from_fred():
    from tradehub.workshop.data import release_dates
    seen = {}

    def get_text(url, params, **kw):
        seen.update(params, url=url)
        return '{"release_dates": [{"release_id": 101, "date": "2026-09-17"}, {"release_id": 101, "date": "2026-10-29"}]}'
    got = release_dates(101, get_text=get_text, api_key="k")
    assert seen["release_id"] == 101 and seen["url"].endswith("/fred/release/dates")
    assert list(got["time"]) == [pd.Timestamp("2026-09-17"), pd.Timestamp("2026-10-29")]


def test_my_own_dates_are_measured_and_judged_like_any_event():
    days = IDX[30:-30:63]
    closes = market(7, drift_after=0.006, events=days)
    s = spec(event="custom", when="all", tickers=[],
             custom=[{"ticker": "aaa", "date": str(d.date()), "surprise": 1.0} for d in days])
    assert s.tickers == ["AAA"]  # tickers come from the pasted rows
    out = run_event_test(s, closes, {}, variations=1, seed=1, permutations=300)
    assert out["n_events"] == len(days) and out["verdict"] == "PASS"
    assert out["events"][0]["date"] == str(days[0].date())  # a pasted date is the reaction day itself


def test_my_own_dates_need_rows_and_take_beat_or_miss():
    with pytest.raises(ValueError, match="dates"):
        spec(event="custom", when="all", tickers=["AAA"], custom=[])
    s = spec(event="custom", when="miss", tickers=[], custom=[{"ticker": "AAA", "date": "2020-01-06", "surprise": -2},
                                                              {"ticker": "AAA", "date": "2020-04-06", "surprise": 3}])
    assert s.when == "miss" and len(s.custom) == 2


def test_a_notebook_table_with_many_tickers_keeps_them_all():
    rows = [{"ticker": f"T{i}", "date": "2020-01-06"} for i in range(14)]
    assert len(spec(event="custom", when="all", tickers=[], custom=rows).tickers) == 14


def test_shared_event_days_are_drawn_together_in_the_random_dates():
    # CodeRabbit #204 (Major): on a shared calendar (FOMC/CPI/jobs) every ticker moves on the same day, so the
    # random-date null must draw ONE random day per event day for all tickers. Five identical tickers then give
    # exactly the one-ticker p-value; drawing each ticker on its own would shrink it.
    closes = market(8)
    for i in range(1, 5):
        closes[f"B{i}"] = closes["AAA"]
    days = [pd.Timestamp(d) for d in IDX[30:-30:40]]
    ev = {"*": pd.DataFrame({"time": days})}
    one = run_event_test(spec(event="fomc", when="all", tickers=["AAA"]), closes, ev, variations=1, seed=5,
                         permutations=400)
    five = run_event_test(spec(event="fomc", when="all", tickers=["AAA", "B1", "B2", "B3", "B4"]), closes, ev,
                          variations=1, seed=5, permutations=400)
    assert five["claim"]["unseen"]["value"] == pytest.approx(one["claim"]["unseen"]["value"])
    assert five["shuffle"]["p"] == pytest.approx(one["shuffle"]["p"])


def test_result_carries_the_pass_marks():
    days = IDX[30:-30:63]
    closes = market(3, drift_after=0.006, events=days)
    out = run_event_test(spec(), closes, _events(closes), variations=1, seed=1, permutations=300)
    assert out["shuffle"]["holds"] is True and out["t_test"]["holds"] in (True, False)
    assert out["periods"]["holds"] in (True, False, None)


def test_earnings_without_a_surprise_column_still_loads():
    from tradehub.workshop.data import earnings_dates
    idx = pd.DatetimeIndex(["2026-07-31 16:30"]).tz_localize("America/New_York")
    raw = pd.DataFrame({"EPS Estimate": [3.6], "Reported EPS": [3.5]}, index=idx)
    got = earnings_dates("XOM", fetch=lambda t: raw, now=pd.Timestamp("2026-10-31 22:00", tz="UTC").to_pydatetime())
    assert len(got) == 1 and got["surprise"].isna().all()


def test_a_fred_outage_is_a_readable_error_not_a_crash():
    from tradehub.workshop.data import UnknownSymbol, release_dates

    def down(url, params, **kw):
        raise RuntimeError("FRED 503 with api_key=secret")
    with pytest.raises(UnknownSymbol) as exc:
        release_dates(101, get_text=down, api_key="secret")
    assert "secret" not in str(exc.value) and "FRED" in str(exc.value)
