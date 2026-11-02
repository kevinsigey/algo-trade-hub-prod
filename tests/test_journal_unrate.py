"""Tests for the KXU3 unemployment-level forecaster (`unrate_nowcast`,
`unrate-level-v1`), built 2026-11-01 on the macro audit's evidence.

Data facts: KXU3 strikes are `greater` at 0.1pp steps, the market closes a
minute before the 8:30 ET jobs report, and settlement grades the first print
of U3 -- the labor stack's own first-print levels.
"""

from datetime import UTC, date, datetime, timedelta

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.unrate_level import fit_unrate_model, unrate_pairs, unrate_prob
from tradehub.journal.forecasters.unrate_level import build_unrate
from tradehub.markets import parse_market

CLOSE = datetime(2026, 12, 4, 13, 29, tzinfo=UTC)  # Dec 4 jobs report, a minute before 8:30 ET
NOW = CLOSE - timedelta(hours=1)
FIRST_MONTH = date(2022, 6, 1)                     # monthly prints ending Oct 2026
N_MONTHS = 53


def _levels(n=N_MONTHS):
    """U3 drifting up slowly with persistent changes: +0.1 most months, flat some."""
    out = [3.6]
    for i in range(1, n):
        out.append(round(out[-1] + (0.0 if i % 4 == 0 else 0.1), 1))
    return out


class _Inputs:
    def __init__(self, levels):
        # vintages: each month's release vintage carries every month printed by then
        self.unrate = {}
        for k in range(len(levels)):
            month = date(FIRST_MONTH.year + (FIRST_MONTH.month - 1 + k) // 12,
                         (FIRST_MONTH.month - 1 + k) % 12 + 1, 1)
            self.unrate[month + timedelta(days=35)] = {
                date(FIRST_MONTH.year + (FIRST_MONTH.month - 1 + j) // 12,
                     (FIRST_MONTH.month - 1 + j) % 12 + 1, 1): levels[j]
                for j in range(k + 1)}


class FakeLaborData:
    def __init__(self, levels):
        self._inputs = _Inputs(levels)

    def inputs(self, now):
        return self._inputs


def _lm(strike=4.5):
    raw = {"ticker": f"KXU3-26NOV-T{strike}", "event_ticker": "KXU3-26NOV",
           "strike_type": "greater", "floor_strike": strike, "cap_strike": None,
           "open_time": "2026-11-01T04:00:00Z", "close_time": CLOSE.isoformat(),
           "title": "Unemployment rate"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=0.40, yes_ask=0.44, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def test_pairs_and_fit_on_persistent_changes():
    pairs = unrate_pairs(_levels())
    assert len(pairs) == N_MONTHS - 2
    model = fit_unrate_model(pairs)
    assert model is not None and model.sigma >= 0.05
    assert fit_unrate_model(pairs[:10]) is None
    assert 0.0 < unrate_prob(_lm().market, mu=9.0, sigma=model.sigma) < 1.0


def test_the_forecaster_freezes_for_the_ended_month_and_forecasts():
    live = FakeLive([_lm()])
    fc, ki, persistence = build_unrate(live, lambda t: None, FakeLaborData(_levels()))
    assert (fc.name, fc.version, fc.cadence) == ("unrate_nowcast", "unrate-level-v1", "monthly")
    assert ki.name == "kalshi_implied_unrate" and persistence.name == "baseline_persistence_unrate"

    assert fc.targets(CLOSE - timedelta(hours=25)) == []
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)
    assert f is not None and 0.0 < f.probability < 1.0
    assert f.payload["last"] == _levels()[-1]
    p = persistence.forecast(persistence.targets(NOW)[0], NOW)
    assert p is not None and p.payload["mu"] == _levels()[-1]
