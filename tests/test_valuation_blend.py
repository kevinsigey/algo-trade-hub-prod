"""Tests for step 10's Guidance method change (Claude's ruling,
2026-11-19): each name's guidance value uses a 50/50 blend of its own
5-year median multiple and the peer median; without 5 years of history
the peer median alone is used and the sheet is flagged peer only.

The own multiple is the median of the last five fiscal years' trailing
P/E at each fiscal year-end (close on or before the period end over
that year's diluted EPS, from EDGAR's annual series).
"""

from datetime import date, datetime, timezone

import pandas as pd

from tradehub.valuation import engine, store
from tradehub.valuation.run import _own_multiple

NOW = datetime(2026, 11, 19, tzinfo=timezone.utc)


def _records():
    return [{"ticker": "ACME", "metric": "eps_adjusted", "period": "FY2027",
             "low": 4.0, "high": 6.0, "unit": "usd_per_share",
             "consensus": 4.2, "consensus_period": "FY2027",
             "created_at": "2026-11-01T00:00:00+00:00", "accession": "0001"}]


def _sheet(**kw):
    kw.setdefault("peer_median_fwd_eps", 4.0)
    kw.setdefault("peer_count", 6)
    kw.setdefault("peer_basis", "industry_group")
    kw.setdefault("guided_peers", [])
    kw.setdefault("fundamentals", {})
    kw.setdefault("price_date", date(2026, 11, 18))
    return engine.build_fact_sheet(ticker="ACME", records=_records(), price=80.0,
                                   peer_multiple=20.0, now=NOW, **kw)


def test_blend_multiple_math():
    assert engine.blend_multiple(10.0, 20.0) == (15.0, "blend")
    assert engine.blend_multiple(None, 20.0) == (20.0, "peer_only")
    assert engine.blend_multiple(10.0, None) == (None, "peer_only")


def test_bands_use_the_blended_multiple():
    sheet = _sheet(own_multiple=10.0)
    assert sheet["multiple_basis"] == "blend"
    assert sheet["own_multiple"] == 10.0
    assert sheet["peer_multiple"] == 20.0
    assert sheet["bands"] == {"bear": round(4.0 * 0.90 * 15.0, 2),
                              "base": round(5.0 * 15.0, 2),
                              "bull": round(6.0 * 15.0, 2)}
    assert sheet["implied"]["eps"] == round(80.0 / 15.0, 4)


def test_peer_only_when_no_own_multiple():
    sheet = _sheet()
    assert sheet["multiple_basis"] == "peer_only"
    assert sheet["own_multiple"] is None
    assert sheet["bands"]["base"] == 100.0   # the peer multiple alone


class _FakeDS:
    """yfinance semantics: `prices(adjusted=False)` closes are still
    split-adjusted (only dividends are left in), and the window is
    `years` back from today, so an old fiscal year-end can fall outside it."""

    def __init__(self, series, closes, splits=(), today=None):
        self._series = series
        idx = pd.DatetimeIndex([d for d, _ in closes])
        self._frame = pd.DataFrame({"ACME": [c for _, c in closes]}, index=idx)
        self._splits = pd.Series([r for _, r in splits],
                                 index=pd.DatetimeIndex([d for d, _ in splits]), dtype=float)
        self._today = pd.Timestamp(today) if today else None
        self.calls = []

    def edgar_annual_series(self, ticker, concept):
        return self._series

    def prices(self, tickers, years=5, adjusted=True):
        self.calls.append({"years": years, "adjusted": adjusted})
        if self._today is None:
            return self._frame
        return self._frame[self._frame.index >= self._today - pd.DateOffset(years=years)]

    def splits(self, ticker):
        return self._splits


def test_own_multiple_is_the_five_year_median():
    series = [("2021-12-31", 2.0), ("2022-12-31", 2.5), ("2023-12-31", 3.0),
              ("2024-12-31", 3.5), ("2025-12-31", 4.0)]
    closes = [("2021-12-31", 50.0), ("2022-12-31", 60.0), ("2023-12-31", 75.0),
              ("2024-12-31", 70.0), ("2025-12-31", 100.0)]
    # multiples 25, 24, 25, 20, 25 -> median 25
    assert _own_multiple(_FakeDS(series, closes), "ACME", NOW) == 25.0


class _Resp:
    def __init__(self, data):
        self.data = data


class _Table:
    def __init__(self, client):
        self._client = client

    def insert(self, row):
        self._client.rows.append(row)
        return self

    def select(self, *_a):
        return self

    def order(self, *_a, **_kw):
        return self

    def execute(self):
        return _Resp(list(self._client.rows))


class _Client:
    def __init__(self):
        self.rows = []

    def table(self, _name):
        return _Table(self)


def test_store_round_trips_the_multiple_fields_via_inputs():
    """No new columns: insert_sheet folds own_multiple / multiple_basis
    into the stored inputs jsonb, and the read helpers lift them back
    to the sheet's top level so served rows match the engine's shape."""
    client = _Client()
    sheet = _sheet(own_multiple=10.0)
    sheet["inputs"] = {"guidance_records": []}
    store.insert_sheet(client, sheet)
    [row] = client.rows
    assert row["inputs"]["own_multiple"] == 10.0
    assert row["inputs"]["multiple_basis"] == "blend"
    [served] = store.latest_sheets(client)
    assert served["own_multiple"] == 10.0
    assert served["multiple_basis"] == "blend"


def test_own_multiple_needs_consecutive_years():
    # 2023 is missing: the last five rows span six years, and a median
    # across a skipped fiscal year blends two regimes (Claude's review).
    gapped = [("2020-12-31", 2.0), ("2021-12-31", 2.5), ("2022-12-31", 3.0),
              ("2024-12-31", 3.5), ("2025-12-31", 4.0)]
    closes = [("2020-12-31", 50.0), ("2021-12-31", 60.0), ("2022-12-31", 75.0),
              ("2024-12-31", 70.0), ("2025-12-31", 100.0)]
    assert _own_multiple(_FakeDS(gapped, closes), "ACME", NOW) is None


def test_own_multiple_needs_a_fresh_newest_year():
    # Five consecutive years, but the newest ended over 18 months ago.
    stale = [("2020-12-31", 2.0), ("2021-12-31", 2.5), ("2022-12-31", 3.0),
             ("2023-12-31", 3.5), ("2024-12-31", 4.0)]
    closes = [("2020-12-31", 50.0), ("2021-12-31", 60.0), ("2022-12-31", 75.0),
              ("2023-12-31", 70.0), ("2024-12-31", 100.0)]
    assert _own_multiple(_FakeDS(stale, closes), "ACME", NOW) is None


def test_own_multiple_needs_five_clean_years():
    four = [("2022-12-31", 2.5), ("2023-12-31", 3.0),
            ("2024-12-31", 3.5), ("2025-12-31", 4.0)]
    closes = [("2022-12-31", 60.0), ("2023-12-31", 75.0),
              ("2024-12-31", 70.0), ("2025-12-31", 100.0)]
    assert _own_multiple(_FakeDS(four, closes), "ACME", NOW) is None
    negative = [("2021-12-31", 2.0), ("2022-12-31", -1.0), ("2023-12-31", 3.0),
                ("2024-12-31", 3.5), ("2025-12-31", 4.0)]
    closes5 = [("2021-12-31", 50.0)] + closes
    assert _own_multiple(_FakeDS(negative, closes5), "ACME", NOW) is None


def test_own_multiple_fetches_back_to_the_earliest_fiscal_year_end():
    # September fiscal years: five years back from today stops after the
    # oldest year-end, so a flat years=5 read fell back to peer-only on a
    # complete history (Claude's #569 review, run.py:152).
    series = [("2021-09-30", 2.0), ("2022-09-30", 2.5), ("2023-09-30", 3.0),
              ("2024-09-30", 3.5), ("2025-09-30", 4.0)]
    closes = [("2021-09-30", 50.0), ("2022-09-30", 60.0), ("2023-09-30", 75.0),
              ("2024-09-30", 70.0), ("2025-09-30", 100.0)]
    ds = _FakeDS(series, closes, today=NOW.date())
    assert _own_multiple(ds, "ACME", NOW) == 25.0


def test_own_multiple_uses_unadjusted_closes_against_as_reported_eps():
    # EDGAR EPS is as reported, so a 2:1 split in mid-2024 halves EPS from
    # then on; the year-end close must be the price that traded that day,
    # not today's split-and-dividend-adjusted one (Kevin's ruling, :159).
    series = [("2021-12-31", 4.0), ("2022-12-31", 5.0), ("2023-12-31", 6.0),
              ("2024-12-31", 3.5), ("2025-12-31", 4.0)]
    # split-adjusted closes, as yfinance serves them: pre-split days halved
    closes = [("2021-12-31", 50.0), ("2022-12-31", 60.0), ("2023-12-31", 75.0),
              ("2024-12-31", 70.0), ("2025-12-31", 100.0)]
    ds = _FakeDS(series, closes, splits=[("2024-06-10", 2.0)])
    # traded prices 100/120/150 pre-split, then 70/100: multiples 25, 24, 25, 20, 25
    assert _own_multiple(ds, "ACME", NOW) == 25.0
    assert all(c["adjusted"] is False for c in ds.calls)
