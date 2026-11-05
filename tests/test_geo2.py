"""The geo2 family (Kevin, 2026-11-04): the sensitive continuous Hormuz
stress (geo/stress.py) widening sigma on the hourly WTI, daily WTI and
daily natgas shadows. The engine is continuous where v2 was binary --
stress below v2's fire lines still moves k -- and conservative where it
must be: a signal that cannot speak never widens, and too few speaking
signals read as no stress at all (k = 1.0, stamped partial).
"""
from datetime import timedelta

import pytest

from tests.test_journal_oil_hourly import NOW, FakeLive, _lm as _hourly_lm
from tests.test_journal_oil import NOW as OIL_NOW, FakeLive as OilFakeLive, _inputs as oil_inputs, _lm as _daily_lm
from tests.test_journal_natgas_daily import NOW as GAS_NOW, FakeLive as GasFakeLive, _inputs as gas_inputs, _lm as _gas_lm
from tradehub.backtest.pit import Observation
from tradehub.geo.stress import sensitive_stress
from tradehub.journal.forecasters.natgas_daily import NatgasDaily
from tradehub.journal.forecasters.oil import OilWti
from tradehub.journal.forecasters.oil_geo2 import (
    NatgasDailyGeo2Shadow,
    OilWtiDailyGeo2Shadow,
    OilWtiHourlyGeo2Shadow,
)
from tradehub.journal.forecasters.oil_hourly import HourlyInputs, OilWtiHourly

BASE = {("ais", "tankers_gate_entries_1h"): 10.0, ("ais", "anchored_tankers"): 2.0,
        ("adsb_jamming", "jamming_intraday"): 0.04, ("gpsjam", "jamming_daily"): 0.03,
        ("adsb", "mil_total"): 2.0, ("adsb", "mil_isr"): 1.0, ("adsb", "mil_tanker"): 1.0,
        ("firms", "frp_terminals"): 0.0}


def _current(overrides=None):
    values = {**BASE, **(overrides or {})}
    return [{"feed": f, "metric": m, "value": v, "health": "live"} for (f, m), v in values.items()]


def _history(n=30):
    return [{"feed": f, "metric": m, "value": v} for (f, m), v in BASE.items() for _ in range(n)]


def test_a_calm_day_reads_zero_stress():
    stress, k, contrib, partial = sensitive_stress(_current(), _history())
    assert stress == 0.0 and k == 1.0 and partial is False


def test_stress_moves_below_the_old_binary_lines():
    # Military at 2x its median fired NOTHING under v2 (its line was 3x).
    stress, k, contrib, partial = sensitive_stress(
        _current({("adsb", "mil_total"): 4.0}), _history())
    assert contrib["military"] == 0.5
    assert stress == pytest.approx(2 * 0.5 / 11) and k > 1.05


def test_a_compound_extreme_reaches_the_cap():
    stress, k, contrib, partial = sensitive_stress(
        _current({("ais", "tankers_gate_entries_1h"): 0.0,
                  ("adsb_jamming", "jamming_intraday"): 0.12,
                  ("gpsjam", "jamming_daily"): 0.09,
                  ("adsb", "mil_total"): 6.0, ("ais", "anchored_tankers"): 6.0,
                  ("firms", "frp_terminals"): 5.0}), _history())
    assert stress == 1.0 and k == 1.75


def test_thin_history_and_dead_feeds_never_widen():
    stress, k, contrib, partial = sensitive_stress(_current(), _history(n=10))
    assert stress is None and k == 1.0 and partial is True
    rows = _current()
    rows[0] = {**rows[0], "health": "unknown"}
    stress, k, contrib, partial = sensitive_stress(rows, _history())
    assert contrib["gate_flow"] == "unavailable" and partial is True and stress is not None


def _provider(current, history):
    return lambda now: (current, history)


def test_hourly_shadow_matches_v1_when_calm_and_widens_under_stress():
    live = FakeLive([_hourly_lm(102)])
    obs = Observation("WTI:CL=F:last", 101.2, NOW - timedelta(minutes=2))
    inputs = HourlyInputs(live, price_fn=lambda: obs)
    calm = OilWtiHourlyGeo2Shadow(live, lambda t: None, inputs, _provider(_current(), _history()))
    v1 = OilWtiHourly(live, lambda t: None, inputs)
    entry = calm.targets(NOW)[0]
    assert calm.forecast(entry, NOW).probability == v1.forecast(v1.targets(NOW)[0], NOW).probability
    hot = OilWtiHourlyGeo2Shadow(live, lambda t: None, inputs, _provider(
        _current({("ais", "tankers_gate_entries_1h"): 0.0, ("adsb", "mil_total"): 6.0}), _history()))
    fc = hot.forecast(hot.targets(NOW)[0], NOW)
    assert fc.payload["geo2_k"] > 1.3 and fc.forecaster_version == "wti-hourly-v5-geo2-shadow"


def test_daily_shadows_recompute_from_the_base_payload():
    oil_live = OilFakeLive([_daily_lm("KXWTI-26NOV0214-T103.49", 103.49)])
    oil = OilWtiDailyGeo2Shadow(oil_live, lambda t: None, oil_inputs(oil_live),
                                _provider(_current({("ais", "tankers_gate_entries_1h"): 0.0}), _history()))
    base = OilWti(oil_live, lambda t: None, oil_inputs(oil_live))
    fc = oil.forecast(oil.targets(OIL_NOW)[0], OIL_NOW)
    b = base.forecast(base.targets(OIL_NOW)[0], OIL_NOW)
    assert fc is not None and b is not None
    assert fc.payload["sigma"] > b.payload["sigma"] and fc.payload["geo2_k"] > 1.0
    assert fc.probability != b.probability

    gas_live = GasFakeLive([_gas_lm(3.09)])
    gas = NatgasDailyGeo2Shadow(gas_live, lambda t: None, gas_inputs(gas_live),
                                _provider(_current({("ais", "tankers_gate_entries_1h"): 0.0}), _history()))
    gbase = NatgasDaily(gas_live, lambda t: None, gas_inputs(gas_live))
    gfc = gas.forecast(gas.targets(GAS_NOW)[0], GAS_NOW)
    gb = gbase.forecast(gbase.targets(GAS_NOW)[0], GAS_NOW)
    assert gfc is not None and gb is not None
    assert gfc.payload["sigma_d"] > gb.payload["sigma_d"] and gfc.probability != gb.probability


def test_the_live_feed_row_keeps_stress_and_anchor_separate_from_the_other_rows():
    from tradehub.journal.forecasters.oil_geo2 import HL_HOURLY_VERSION, HOURLY_VERSION, OilWtiHourlyHlGeo2Shadow, build_oil_geo2
    from tradehub.journal.forecasters.oil_hl import _hl_price_or_none

    live = type("L", (), {"open_markets": lambda self, s: [], "settled_values_recent": lambda self, s, n: []})()
    rows = build_oil_geo2(live, fetch=lambda t: None, provider=lambda now: ([], []))
    row = next(f for f in rows if isinstance(f, OilWtiHourlyHlGeo2Shadow))
    assert row.name == "oil_wti_hourly" and row.version == HL_HOURLY_VERSION == "wti-hourly-v6-hl-geo2-shadow"
    assert row._inputs._price_fn is _hl_price_or_none
    assert HL_HOURLY_VERSION != HOURLY_VERSION
