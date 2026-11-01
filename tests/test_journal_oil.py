"""Tests for the Kalshi daily WTI forecaster (`oil_wti`, `wti-v1`), built 2026-11-01 on the
weather/energy audit's evidence.

Data facts: KXWTI settles on the day's ICE WTI settlement (~14:30 ET; the Nov 2 event's
close_time is 2026-11-02T19:30:00Z), its event ticker carries a settlement-hour suffix
(KXWTI-26NOV0214), and settlements skip weekends -- so training changes are per-day across
their gap. The model is the oil engine's regression of the per-day settlement change on the
CL=F 5-close change, fit and applied at the same decision time (close minus the 2h lead).
"""

import statistics
from datetime import UTC, date, datetime, timedelta

import pytest
from journal_fakes import FakeJournalDB

from tradehub.backtest.pit import Observation
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.oil import OilModel, oil_prob, settlement_daily_changes
from tradehub.journal.forecasters.oil import (
    MIN_TRAIN,
    VERSION,
    OilInputs,
    OilPersistence,
    OilWti,
    build_oil,
)
from tradehub.journal.runner import run_journal
from tradehub.markets import event_date, parse_market

CLOSE = datetime(2026, 11, 2, 19, 30, tzinfo=UTC)   # 14:30 EST settlement, Nov 2
NOW = CLOSE - timedelta(hours=1)                    # inside the 2h freeze window
DAY = date(2026, 11, 2)


def _lm(ticker, floor, bid=0.40, ask=0.44, close=CLOSE):
    event = ticker.rsplit("-", 1)[0]
    raw = {"ticker": ticker, "event_ticker": event, "strike_type": "greater", "floor_strike": floor,
           "cap_strike": None, "open_time": "2026-11-01T04:00:00Z", "close_time": close.isoformat(),
           "title": ticker}
    return LiveMarket(parse_market(raw), Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=5.0, yes_ask_size=5.0))


class FakeLive:
    def __init__(self, markets, settled=None):
        self.markets = markets
        self.settled = _settled() if settled is None else settled

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]

    def settled_values(self, series):
        return self.settled


def _settled(n=45):
    """Business-day settlements ending Fri Oct 30, 2026 (the last before the Nov 2 event)."""
    out = []
    day = date(2026, 8, 31)
    while len(out) < n:
        if day.weekday() < 5:
            i = len(out)
            out.append(Observation(f"KXWTI-{day.strftime('%y%b%d').upper()}14",
                                   100.0 + i * 0.1 + (0.4 if i % 2 else -0.4),
                                   datetime(day.year, day.month, day.day, 20, tzinfo=UTC)))
        day += timedelta(days=1)
    return out


def _closes(n=20):
    return [Observation(f"WTI:CL=F:2026-10-{day:02d}", 100.0 + i * 0.2,
                        datetime(2026, 10, day, 23, tzinfo=UTC)) for i, day in enumerate(range(1, n + 1))]


def _inputs(live):
    return OilInputs(live, closes_fn=lambda: _closes())


def test_the_forecaster_freezes_only_inside_the_two_hour_window():
    live = FakeLive([_lm("KXWTI-26NOV0214-T90.49", 90.49)])
    fc = OilWti(live, lambda t: None, _inputs(live))

    assert fc.targets(NOW)
    assert fc.targets(CLOSE - timedelta(hours=2, minutes=1)) == []
    assert fc.targets(CLOSE - timedelta(hours=3)) == []
    assert fc.targets(CLOSE + timedelta(hours=1)) == []


def test_the_model_forecasts_the_settlement_day_from_fridays_settlement():
    live = FakeLive([_lm("KXWTI-26NOV0214-T90.49", 90.49)])
    fc = OilWti(live, lambda t: None, _inputs(live))
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)

    assert (fc.name, fc.version, fc.cadence) == ("oil_wti", VERSION, "daily")
    assert f.market_prob == pytest.approx(0.42)
    # Fri Oct 30 settlement -> Mon Nov 2 target: a 3-day horizon over the weekend gap.
    assert f.payload["horizon_days"] == 3
    assert f.payload["last_settlement_event"] == "KXWTI-26OCT3014"
    assert f.payload["yes_bid"] == 0.40
    assert 0.0 <= f.probability <= 1.0


def test_the_persistence_baseline_is_the_last_settlement_with_past_daily_sigma():
    live = FakeLive([_lm("KXWTI-26NOV0214-T90.49", 90.49)])
    fc = OilPersistence(live, lambda t: None, _inputs(live))
    [entry] = fc.targets(NOW)
    f = fc.forecast(entry, NOW)

    assert fc.name == "baseline_persistence_oil"
    settled = _settled()
    sigma = max(0.25, statistics.stdev(settlement_daily_changes(settled)))
    last = max(settled, key=lambda o: event_date(o.name))
    assert f.probability == pytest.approx(
        oil_prob(live.markets[0].market, last.value, 3, None, OilModel(0.0, 0.0, sigma)))
    assert f.payload["sigma"] == pytest.approx(sigma)


def test_daily_changes_are_normalized_across_the_weekend_gap():
    settled = _settled()
    changes = settlement_daily_changes(settled)
    fri = next(o for o in settled if event_date(o.name).weekday() == 4)
    mon = next(o for o in settled if event_date(o.name) > event_date(fri.name))
    gap = (event_date(mon.name) - event_date(fri.name)).days
    assert gap == 3
    assert (mon.value - fri.value) / 3 in changes


def test_too_little_history_is_a_gap_not_a_guess():
    live = FakeLive([_lm("KXWTI-26NOV0214-T90.49", 90.49)], settled=_settled(MIN_TRAIN - 1))
    inputs = _inputs(live)
    for cls in (OilWti, OilPersistence):
        fc = cls(live, lambda t: None, inputs)
        [entry] = fc.targets(NOW)
        assert fc.forecast(entry, NOW) is None


def _final(result):
    return lambda ticker: {"market": {"ticker": ticker, "status": "finalized", "result": result}}


def test_end_to_end_the_model_baseline_and_market_are_scored_on_the_same_contracts():
    clock = [NOW]
    db = FakeJournalDB(lambda: clock[0])
    live = FakeLive([_lm("KXWTI-26NOV0214-T90.49", 90.49),
                     _lm("KXWTI-26NOV0214-T91.49", 91.49)])
    inputs = _inputs(live)
    fcs = build_oil(live, _final("yes"), inputs)
    run_journal(db, fcs, clock[0])
    clock[0] = CLOSE + timedelta(hours=1)
    out = run_journal(db, fcs, clock[0])

    assert not out["failures"]
    cards = {r["forecaster"]: r for r in db.tables["journal_scores"]}
    assert cards["oil_wti"]["n_settled"] == 2 and cards["oil_wti"]["baseline"] == "market"
    assert cards["baseline_persistence_oil"]["n_settled"] == 2
    assert cards["kalshi_implied_oil"]["bss"] == pytest.approx(0.0)


def test_the_registry_carries_oil_and_its_cautious_row():
    from tradehub.journal.registry import FORECASTERS

    names = [(f.name, getattr(f, "version", None)) for f in FORECASTERS]
    assert ("oil_wti", "wti-v1") in names
    assert ("oil_wti_cautious", "wti-v1+w25") in names
    assert ("baseline_persistence_oil", "v1") in names
