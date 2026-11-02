"""Tests for the PPI YoY forecaster (`ppi_nowcast`, `ppi-yoy-v1`), built
2026-11-01 on the macro audit's medium-add verdict.

Data facts: KXUSPPIYOY's event ticker carries the *release date*
(KXUSPPIYOY-26NOV13), the market closes a minute before the 8:30 ET release,
strikes are `greater` at 0.1pp steps, and settlement grades the YoY first
print -- computed here from ALFRED first prints of the final-demand index.
"""

from datetime import UTC, date, datetime, timedelta

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.labor import add_months, month_end
from tradehub.engines.ppi_yoy import fit_ppi_model, ppi_pairs, ppi_prob
from tradehub.journal.forecasters.ppi import PpiData, build_ppi
from tradehub.markets import parse_market

CLOSE = datetime(2026, 11, 13, 13, 29, tzinfo=UTC)  # Nov 13 PPI release, a minute before 8:30 ET
NOW = CLOSE - timedelta(hours=1)
FIRST = date(2019, 1, 1)
N_LEVELS = 93  # Jan 2019 .. Sep 2026 -> YoY prints Jan 2020 .. Sep 2026


def _month(k):
    return add_months(FIRST, k)


def _levels(n=N_LEVELS):
    """Final-demand index compounding ~0.55%/mo, faster after month 60."""
    out = [100.0]
    for i in range(1, n):
        out.append(out[-1] * (1.0 + (0.0085 if i > 60 else 0.0055)))
    return out


def _vintages(levels):
    """{month-end: {month: level}} -- the vintage after a month's print carries
    every level published by then; first_prints picks each out of its first."""
    out = {}
    for k in range(len(levels)):
        out[month_end(_month(k)) + timedelta(days=20)] = {_month(j): levels[j] for j in range(k + 1)}
    return out


def _data(levels=None):
    vintages = _vintages(_levels() if levels is None else levels)
    return PpiData(fetch=lambda series, days, **kw: vintages)


def _lm(strike=7.2):
    raw = {"ticker": f"KXUSPPIYOY-26NOV13-T{strike}", "event_ticker": "KXUSPPIYOY-26NOV13",
           "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
           "open_time": "2026-11-01T04:00:00Z", "close_time": CLOSE.isoformat(),
           "title": "PPI year over year"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=0.40, yes_ask=0.44, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def test_yoy_series_comes_from_first_print_levels():
    series = _data().yoy(NOW)
    assert series[0][0] == date(2020, 1, 1) and series[-1][0] == date(2026, 9, 1)
    assert all(5.0 < v < 12.0 for _, v in series)
    pairs = ppi_pairs([v for _, v in series])
    model = fit_ppi_model(pairs)
    assert model is not None and model.sigma >= 0.05
    assert fit_ppi_model(pairs[:10]) is None


def test_the_forecaster_freezes_for_the_release_and_forecasts():
    live = FakeLive([_lm()])
    fc, ki, persistence = build_ppi(live, lambda t: None, _data())
    assert (fc.name, fc.version, fc.cadence) == ("ppi_nowcast", "ppi-yoy-v1", "monthly")
    assert ki.name == "kalshi_implied_ppi" and persistence.name == "baseline_persistence_ppi"

    assert fc.targets(CLOSE - timedelta(hours=25)) == []
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)
    assert f is not None and 0.0 < f.probability < 1.0
    assert 0.0 < ppi_prob(_lm().market, mu=f.payload["mu"], sigma=max(f.payload["sigma"], 0.05)) < 1.0
    p = persistence.forecast(persistence.targets(NOW)[0], NOW)
    assert p is not None and p.payload["mu"] == f.payload["last"]
