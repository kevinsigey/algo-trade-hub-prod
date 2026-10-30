from datetime import date

import pandas as pd
import pytest

from tradehub.workshop.data import UnknownSymbol, closes, fred_series

IDX = pd.bdate_range("2020-01-01", "2020-01-10")


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
    df = closes(["SPY", "GLD"], date(2020, 1, 1), download=fake_download(calls), today=date(2020, 1, 11))
    assert list(df.columns) == ["SPY", "GLD"] and df["GLD"].iloc[0] == 20


def test_empty_ticker_is_unknown_symbol():
    with pytest.raises(UnknownSymbol, match="XYZ"):
        closes(["SPY", "XYZ"], date(2020, 1, 1), download=fake_download([]), today=date(2020, 1, 11))


def test_fresh_cache_skips_download_and_stale_refetches(tmp_path):
    calls = []
    closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, today=date(2020, 1, 11))
    closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, today=date(2020, 1, 11))
    assert len(calls) == 1  # Saturday: Friday's close is the latest there is
    closes(["SPY"], date(2020, 1, 1), download=fake_download(calls), cache_dir=tmp_path, today=date(2020, 1, 15))
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
