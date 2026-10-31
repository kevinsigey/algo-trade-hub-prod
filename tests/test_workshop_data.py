from datetime import UTC, date, datetime

import pandas as pd
import pytest

from tradehub.workshop.data import UnknownSymbol, closes, fred_series

IDX = pd.bdate_range("2020-01-01", "2020-01-10")
SAT_EVENING = datetime(2020, 1, 11, 23, tzinfo=UTC)


def fake_download(calls):
    def download(tickers, start=None, auto_adjust=True, progress=False):
        calls.append(list(tickers))
        cols = pd.MultiIndex.from_product([["Close", "Open"], tickers])
        df = pd.DataFrame(1.0, index=IDX, columns=cols)
        for i, t in enumerate(tickers):
            df[("Close", t)] = range(10 * (i + 1), 10 * (i + 1) + len(IDX))
            if t == "XYZ":
                df[("Close", t)] = float("nan")
        return df
    return download


def test_columns_in_requested_order():
    calls = []
    df = closes(["SPY", "GLD"], date(2020, 1, 1), download=fake_download(calls), now=SAT_EVENING)
    assert list(df.columns) == ["SPY", "GLD"] and df["GLD"].iloc[0] == 20


def test_empty_ticker_is_unknown_symbol():
    with pytest.raises(UnknownSymbol, match="XYZ"):
        closes(["SPY", "XYZ"], date(2020, 1, 1), download=fake_download([]), now=SAT_EVENING)


def test_fresh_cache_skips_download_and_stale_refetches(tmp_path):
    calls = []
    closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, now=SAT_EVENING)
    closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, now=SAT_EVENING)
    assert len(calls) == 1  # Saturday: Friday's close is the latest there is
    closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, now=datetime(2020, 1, 15, 23, tzinfo=UTC))
    assert len(calls) == 2


def test_fred_series_and_empty():
    s = fred_series("DGS10", date(2020, 1, 1), fetch=lambda sid, start: {date(2020, 1, 2): 1.5, date(2020, 1, 3): 1.6})
    assert s.loc["2020-01-03"] == 1.6 and isinstance(s.index, pd.DatetimeIndex)
    with pytest.raises(UnknownSymbol, match="NOPE"):
        fred_series("NOPE", date(2020, 1, 1), fetch=lambda sid, start: {})


def test_fred_http_error_is_unknown_symbol_but_missing_key_is_not():
    def bad(sid, start):
        raise RuntimeError("HTTP 400 Bad Request: series does not exist")
    with pytest.raises(UnknownSymbol, match="NOPE"):
        fred_series("NOPE", date(2020, 1, 1), fetch=bad)

    def nokey(sid, start):
        raise RuntimeError("FRED_API_KEY is not set; the journal's daily series need the keyed FRED API")
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        fred_series("DGS10", date(2020, 1, 1), fetch=nokey)


def test_non_daily_fred_series_is_refused():
    # Review finding 1: a monthly series is published weeks after its observation date; using it by that date leaks.
    monthly = {date(2020, m, 1): float(m) for m in range(1, 13)}
    with pytest.raises(UnknownSymbol, match="daily"):
        fred_series("UNRATE", date(2020, 1, 1), fetch=lambda sid, start: monthly)
    weekly = {date(2020, 1, 4) + __import__("datetime").timedelta(days=7 * i): 1.0 for i in range(20)}
    with pytest.raises(UnknownSymbol, match="daily"):
        fred_series("ICSA", date(2020, 1, 1), fetch=lambda sid, start: weekly)


def test_todays_partial_bar_is_never_returned_or_cached(tmp_path):
    # Review finding 1: a market-hours read must not put today's in-progress price in the cache, where the
    # evening shadow job would record it forever.
    calls = []
    friday_morning = datetime(2020, 1, 10, 15, tzinfo=UTC)  # 10:00 New York
    df = closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, now=friday_morning)
    assert df.index[-1] == pd.Timestamp("2020-01-09")
    assert pd.read_csv(tmp_path / "SPY.csv", index_col=0, parse_dates=True).index[-1] == pd.Timestamp("2020-01-09")
    friday_evening = datetime(2020, 1, 10, 23, tzinfo=UTC)  # 18:00 New York: Friday has closed
    df = closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, now=friday_evening)
    assert len(calls) == 2 and df.index[-1] == pd.Timestamp("2020-01-10")


def fake_bars(calls):
    def download(tickers, start=None, auto_adjust=True, progress=False):
        calls.append(list(tickers))
        cols = pd.MultiIndex.from_product([["Open", "High", "Low", "Close", "Volume"], tickers])
        df = pd.DataFrame(1.0, index=IDX, columns=cols)
        for t in tickers:
            base = pd.Series(range(100, 100 + len(IDX)), index=IDX, dtype=float)
            df[("Open", t)], df[("High", t)], df[("Low", t)], df[("Close", t)] = base, base + 2, base - 2, base + 1
            df[("Volume", t)] = 1000.0
        return df
    return download


def test_bars_columns_cut_and_cache(tmp_path):
    from tradehub.workshop.data import bars
    calls = []
    friday_morning = datetime(2020, 1, 10, 15, tzinfo=UTC)
    out = bars(["SPY"], date(2020, 1, 1), download=fake_bars(calls), cache_dir=tmp_path, now=friday_morning)
    spy = out["SPY"]
    assert list(spy.columns) == ["open", "high", "low", "close", "volume"] and spy.index[-1] == pd.Timestamp("2020-01-09")
    assert spy["high"].iloc[0] == spy["open"].iloc[0] + 2
    assert (tmp_path / "SPY.ohlcv.csv").exists() and not (tmp_path / "SPY.csv").exists()
    bars(["SPY"], date(2020, 1, 1), download=fake_bars(calls), cache_dir=tmp_path, now=friday_morning)
    assert len(calls) == 1
    with pytest.raises(UnknownSymbol, match="XYZ"):
        bars(["XYZ"], date(2020, 1, 1), download=lambda *a, **k: pd.DataFrame(), now=friday_morning)


def test_with_rule_bars_only_for_intraday_exits():
    from tradehub.workshop.data import with_rule_bars
    from tradehub.workshop.spec import IdeaSpec
    prices = pd.DataFrame({"GLD": [1.0, 2.0]}, index=pd.bdate_range("2020-01-02", periods=2))
    plain = IdeaSpec(title="gold", hold=["GLD"], claim="beats_benchmark", exits={"stop_loss_pct": 5})
    assert with_rule_bars(plain, prices, date(2020, 1, 1), bars_fn=lambda *a: 1 / 0) is prices
    plain.exits.mode = "intraday"
    got = with_rule_bars(plain, prices, date(2020, 1, 1), bars_fn=lambda t, s: {
        "GLD": pd.DataFrame({"open": [1.0, 2.0], "high": [1.1, 2.2], "low": [0.9, 1.8], "close": [1.0, 2.0],
                             "volume": [5.0, 6.0]},
                            index=prices.index)})
    assert list(got.columns) == ["GLD", "GLD.open", "GLD.high", "GLD.low", "GLD.volume"]


def test_old_ohlc_cache_ignored(tmp_path):
    from tradehub.workshop.data import bars
    pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0}, index=IDX).to_csv(tmp_path / "SPY.ohlc.csv")
    calls = []
    out = bars(["SPY"], date(2020, 1, 1), download=fake_bars(calls), cache_dir=tmp_path,
               now=datetime(2020, 1, 10, 15, tzinfo=UTC))
    assert calls == [["SPY"]] and "volume" in out["SPY"]


def test_vwap_rule_gets_bars():
    from tradehub.workshop.data import with_rule_bars
    from tradehub.workshop.spec import IdeaSpec
    prices = pd.DataFrame({"GLD": [1.0, 2.0], "SPY": [3.0, 4.0]}, index=pd.bdate_range("2020-01-02", periods=2))
    vwap = {"source": "price", "series": "SPY", "measure": "vs_vwap", "lookback_days": 5, "op": ">", "threshold": 0}
    s = IdeaSpec(title="gold on SPY vwap", hold=["GLD"], claim="beats_benchmark", rules={"enter": {"conditions": [vwap]}},
                 exits={"stop_loss_pct": 5, "mode": "intraday"})
    asked = []

    def fn(tickers, start):
        asked.append(list(tickers))
        return {t: pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 9.0}, index=prices.index)
                for t in tickers}
    got = with_rule_bars(s, prices, date(2020, 1, 1), bars_fn=fn)
    assert asked == [["GLD", "SPY"]] and "SPY.volume" in got and "GLD.open" in got
