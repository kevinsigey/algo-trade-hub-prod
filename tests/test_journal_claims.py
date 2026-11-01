"""Tests for the weekly jobless-claims forecaster (`claims_nowcast`, `claims-v1`),
built 2026-11-01 on the macro audit's evidence.

Data facts: KXJOBLESSCLAIMS strikes are `greater_or_equal` at round thousands, the
market closes 13:25Z on the Thursday release (five minutes before the 8:30 ET print),
and the series settles on the DOL *initial* print -- so the model's history is ALFRED
first prints, snapshot at Thursday vintages.
"""

from datetime import UTC, date, datetime, timedelta

from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.claims import claims_pairs, claims_prob, fit_claims_model
from tradehub.journal.forecasters.claims import ClaimsData, build_claims
from tradehub.markets import parse_market, yes_interval

CLOSE = datetime(2026, 11, 5, 13, 25, tzinfo=UTC)  # Thu Nov 5, five minutes before the print
NOW = CLOSE - timedelta(hours=1)
FIRST_SAT = date(2025, 9, 6)                        # 60 weekly prints ending Sat Oct 24, 2026
N_WEEKS = 60


def _values(n=N_WEEKS):
    """Mean-reverting prints around 215k: a high print is followed by a lower one."""
    out = [215_000.0]
    for i in range(1, n):
        out.append(out[-1] + (215_000.0 - out[-1]) * 0.4 + (3_000.0 if i % 3 == 0 else -1_500.0))
    return out


def _vintages(values):
    """{release Thursday: {week-ending Saturday: value}} -- each vintage carries every
    print published by then; first_prints picks each Saturday out of its first vintage."""
    out = {}
    for k, v in enumerate(values):
        sat = FIRST_SAT + timedelta(days=7 * k)
        out[sat + timedelta(days=5)] = {FIRST_SAT + timedelta(days=7 * j): values[j] for j in range(k + 1)}
    return out


def _data(values=None):
    vintages = _vintages(_values() if values is None else values)
    return ClaimsData(fetch=lambda series, days, **kw: vintages)


def _lm(floor=215_000, ticker_suffix="215000", close=CLOSE):
    raw = {"ticker": f"KXJOBLESSCLAIMS-26NOV05-{ticker_suffix}", "event_ticker": "KXJOBLESSCLAIMS-26NOV05",
           "strike_type": "greater_or_equal", "floor_strike": floor, "cap_strike": None,
           "open_time": "2026-11-01T04:00:00Z", "close_time": close.isoformat(),
           "title": "Initial jobless claims"}
    return LiveMarket(parse_market(raw), Quote(yes_bid=0.40, yes_ask=0.44, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def test_greater_or_equal_settles_at_the_floor_itself():
    market = _lm().market
    lo, hi = yes_interval(market, 1.0)
    assert lo == 215_000 - 0.5 and hi == float("inf")
    # A print AT the floor resolves YES, so a forecast centered on the floor is > 1/2 --
    # under a plain "greater" reading it would be < 1/2.
    assert claims_prob(market, mu=215_000.0, sigma=10_000.0) > 0.5


def test_pairs_and_fit_recover_mean_reversion():
    pairs = claims_pairs(_values())
    assert len(pairs) == N_WEEKS - 4
    model = fit_claims_model(pairs)
    assert model is not None and model.beta > 0 and model.sigma >= 5_000  # beta > 0 on the (avg4 - last) gap IS the reversion pull
    assert fit_claims_model(pairs[:10]) is None


def test_the_forecaster_freezes_inside_the_lead_and_forecasts():
    live = FakeLive([_lm()])
    fc, ki, persistence = build_claims(live, lambda t: None, _data())
    assert (fc.name, fc.version, fc.cadence) == ("claims_nowcast", "claims-v1", "weekly")
    assert ki.name == "kalshi_implied_claims" and persistence.name == "baseline_persistence_claims"

    assert fc.targets(CLOSE - timedelta(hours=25)) == []
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)
    assert f is not None and 0.0 < f.probability < 1.0
    assert f.payload["n_train"] == N_WEEKS - 4
    p = persistence.forecast(persistence.targets(NOW)[0], NOW)
    assert p is not None and p.payload["mu"] == _values()[-1]


def test_a_stale_history_forecasts_nothing():
    values = _values()
    stale = ClaimsData(fetch=lambda series, days, **kw: _vintages(values[:-3]))  # last print 3 weeks old
    fc, _, _ = build_claims(FakeLive([_lm()]), lambda t: None, stale)
    assert fc.targets(NOW) == []
