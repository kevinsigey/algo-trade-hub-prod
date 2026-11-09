"""The metals 15-minute family (Kevin, 2026-11-09; preregistration
docs/superpowers/specs/2026-11-09-metals-fifteen-prereg.md): KXGOLD15M /
KXSILVER15M / KXCOPPER15M forecasters mirroring the oil family
construction-for-construction -- same drift-scaled walk, same fee-netted
0.10 gate in the same code, same halt -- with a fully separate forward
record that opens at PREREG_AT. Copper's weak tape basis is a recorded
risk the record judges, not a reason to exclude it unseen.
"""
from datetime import UTC, datetime, timedelta

import pytest

from tradehub import metals_fifteen_rule as metals
from tradehub import oil_fifteen_rule as oil_rule
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engines.fifteen_min import SERIES_COINS
from tradehub.journal.forecasters.fifteen_min import FifteenMinInputs, build_fifteen_min
from tradehub.markets import KalshiMarket
from tests.test_fifteen_min import T0, _Live, _tape


# ── the series map and the build ─────────────────────────────────────────────

def test_the_engine_maps_each_metals_series_to_its_xyz_coin():
    assert SERIES_COINS["KXGOLD15M"] == "xyz:GOLD"
    assert SERIES_COINS["KXSILVER15M"] == "xyz:SILVER"
    assert SERIES_COINS["KXCOPPER15M"] == "xyz:COPPER"


def test_the_build_covers_the_metals_forecasters_and_their_market_rows():
    built = build_fifteen_min(_Live([]), inputs=FifteenMinInputs(candles_fn=lambda c, s, e: []))
    names = {f.name for f in built}
    assert {"gold_15m", "silver_15m", "copper_15m",
            "kalshi_implied_gold_15m", "kalshi_implied_silver_15m",
            "kalshi_implied_copper_15m"} <= names
    versions = {f.name: f.version for f in built if not f.name.startswith("kalshi_implied")}
    assert versions["gold_15m"] == "gold-15m-v1"
    assert versions["silver_15m"] == "silver-15m-v1"
    assert versions["copper_15m"] == "copper-15m-v1"


def _gold_market(close_time):
    return LiveMarket(
        market=KalshiMarket(ticker="KXGOLD15M-26NOV040030-30", event_ticker="KXGOLD15M-26NOV040030",
                            series_ticker="KXGOLD15M", strike_type="greater_or_equal",
                            floor_strike=None, cap_strike=None,
                            open_time=close_time - timedelta(minutes=15), close_time=close_time,
                            title="Gold price up in next 15 mins?"),
        quote=Quote(yes_bid=0.48, yes_ask=0.52, yes_bid_size=10.0, yes_ask_size=10.0))


def test_a_gold_forecast_reads_the_gold_tape_and_stamps_its_own_version():
    now = T0 + timedelta(minutes=5)
    live = _Live([_gold_market(T0 + timedelta(minutes=15))])
    inputs = FifteenMinInputs(candles_fn=lambda coin, s, e: _tape())
    model = next(f for f in build_fifteen_min(live, inputs=inputs) if f.name == "gold_15m")
    entry = model.targets(now)[0]
    fc = model.forecast(entry, now)
    assert fc is not None and fc.forecaster == "gold_15m" and fc.forecaster_version == "gold-15m-v1"
    assert fc.payload["feed"] == "xyz:GOLD"
    assert fc.payload["open_price"] == 100.0 and fc.payload["remaining_min"] == 10.0


def test_the_live_read_covers_the_metals_series_with_their_labels():
    from tradehub.oil_live import fifteen_live

    now = T0 + timedelta(minutes=5)
    inputs = FifteenMinInputs(candles_fn=lambda coin, s, e: _tape())
    live = _Live([_gold_market(T0 + timedelta(minutes=15))])
    out = fifteen_live(now, live=live, inputs=inputs)
    by_series = {m["series"]: m for m in out["markets"]}
    assert by_series["KXGOLD15M"]["label"] == "Gold"
    assert by_series["KXSILVER15M"]["label"] == "Silver"
    assert by_series["KXCOPPER15M"]["label"] == "Copper"
    assert by_series["KXGOLD15M"]["state"] == "live"


# ── the preregistered gate: shared code, frozen constants ────────────────────

def test_the_metals_gate_is_the_family_gate_not_a_copy():
    assert metals.MIN_EDGE == oil_rule.MIN_EDGE == 0.10
    assert metals.evaluate is oil_rule.evaluate
    assert metals.pick_net is oil_rule.pick_net
    assert metals.pnl is oil_rule.pnl
    assert metals.READY_TRADES == 300
    assert metals.PREREG_AT == "2026-11-09T21:30:00+00:00"
    assert metals.SERIES == (("gold_15m", "gold-15m-v1", "Gold"),
                             ("silver_15m", "silver-15m-v1", "Silver"),
                             ("copper_15m", "copper-15m-v1", "Copper"))


def test_halt_parity_with_the_oil_family():
    # Metals halt at the same Globex hour: a window frozen inside 16:45-18:30 ET
    # is a halt skip under the shared evaluation, and the session shape is the
    # same function, not a re-implementation.
    assert metals.futures_open is oil_rule.futures_open
    halt = metals.evaluate(0.90, yes_ask=0.50, yes_bid=0.48,
                           frozen_at="2026-11-13T21:50:00+00:00")  # 16:50 ET
    assert halt["action"] == "skip" and halt["reason"] == "halt"
    live = metals.evaluate(0.90, yes_ask=0.50, yes_bid=0.48,
                           frozen_at="2026-11-13T21:20:00+00:00")  # 16:20 ET
    assert live["action"] == "buy"


def test_the_gate_is_fee_net_on_a_metals_shaped_quote():
    # 10.5 points gross over the ask is not a trade once the fee is netted;
    # the family's own refusal, exercised through the metals module.
    assert metals.pick_net(0.615, yes_ask=0.51, yes_bid=0.49) is None
    side, cost, edge = metals.pick_net(0.63, yes_ask=0.51, yes_bid=0.49)
    assert (side, cost) == ("yes", 0.51) and edge == pytest.approx(0.12 - 0.07 * 0.51 * 0.49)


# ── the record: separate, gated-counted, prereg-gated ────────────────────────

class FakeSupa:
    """Only what record() reads, through the journal store's helpers."""


def _patch_record(monkeypatch, rows, settlements, tables=None):
    monkeypatch.setattr(metals.store, "fetch_forecasts", lambda supa, f, v: rows.get((f, v), []))
    monkeypatch.setattr(metals.store, "fetch_settlements", lambda supa, targets: settlements)
    monkeypatch.setattr(metals.store, "select_all",
                        lambda supa, table, build, order: (tables or {}).get(table, []))


def test_record_counts_only_forward_rows_and_reports_gated_beside_raw(monkeypatch):
    after = "2026-11-10T15:05:00+00:00"    # after PREREG_AT, outside the halt
    before = "2026-11-09T15:05:00+00:00"   # before PREREG_AT: never evidence
    rows = {("gold_15m", "gold-15m-v1"): [
        {"target": "g1", "probability": 0.70, "payload": {"yes_ask": 0.50, "yes_bid": 0.48},
         "frozen_at": after},
        {"target": "g0", "probability": 0.70, "payload": {"yes_ask": 0.50, "yes_bid": 0.48},
         "frozen_at": before},
    ]}
    _patch_record(monkeypatch, rows, {"g1": 1, "g0": 1})
    out = metals.record(FakeSupa())
    assert out["prereg_at"] == metals.PREREG_AT and out["ready_trades"] == 300
    assert out["forward"]["n"] == 1 and out["replay"]["n"] == 1
    assert out["by_series"]["Gold"]["n"] == 1
    assert out["gate"]["by_series"]["Gold"]["n"] == 1  # 0.70 vs a 0.50 ask clears the net gate too
    assert out["bar"]["basis"] == "gated" and out["bar"]["trades"] == 1
    assert out["bar"]["ready"] is False  # 1 of 300: accruing, honestly not ready
    assert [t["series"] for t in out["recent"]] == ["Gold", "Gold"]


def test_record_decisions_summary_counts_only_metals_series(monkeypatch):
    # The decisions/offsets tables are shared with the oil family; each
    # family's summary reads only its own series' rows.
    tables = {metals.DECISIONS_TABLE: [
        {"series": "KXGOLD15M", "action": "buy", "reason": None},
        {"series": "KXWTI15M", "action": "buy", "reason": None},
        {"series": "KXSILVER15M", "action": "skip", "reason": "no_edge"},
    ]}
    _patch_record(monkeypatch, {}, {}, tables)
    out = metals.record(FakeSupa())
    assert out["decisions"] == {"recorded": 2, "buy": 1, "skip": 1, "by_reason": {"no_edge": 1}}


def test_the_oil_record_never_counts_metals_decisions(monkeypatch):
    tables = {"fifteen_rule_decisions": [
        {"series": "KXGOLD15M", "action": "buy", "reason": None},
        {"series": "KXWTI15M", "action": "skip", "reason": "halt"},
    ], "fifteen_window_offsets": []}
    monkeypatch.setattr(oil_rule.store, "fetch_forecasts", lambda supa, f, v: [])
    monkeypatch.setattr(oil_rule.store, "select_all",
                        lambda supa, table, build, order: tables.get(table, []))
    out = oil_rule.record(FakeSupa())
    assert out["decisions"] == {"recorded": 1, "buy": 0, "skip": 1, "by_reason": {"halt": 1}}


def test_the_route_carries_the_metals_block_beside_the_oil_record(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    rows = {("gold_15m", "gold-15m-v1"): [
        {"target": "g1", "probability": 0.70, "payload": {"yes_ask": 0.50, "yes_bid": 0.48},
         "frozen_at": "2026-11-10T15:05:00+00:00"}]}
    monkeypatch.setattr(metals.store, "fetch_forecasts", lambda supa, f, v: rows.get((f, v), []))
    monkeypatch.setattr(metals.store, "fetch_settlements", lambda supa, targets: {"g1": 1})
    monkeypatch.setattr(metals.store, "select_all", lambda supa, table, build, order: [])
    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        body = TestClient(main.app).get("/api/oil/fifteen-rule").json()
    finally:
        main.app.dependency_overrides.clear()
    assert set(body["metals"]["by_series"]) == {"Gold", "Silver", "Copper"}
    assert body["metals"]["gate"]["by_series"]["Gold"]["n"] == 1
    assert body["metals"]["prereg_at"] == metals.PREREG_AT
    # The oil family's own numbers are untouched by the metals block.
    assert body["forward"]["n"] == 0 and "Gold" not in body["by_series"]


# ── the tracking pass writes metals decisions like the family's ──────────────

def test_tracking_writes_metals_decisions_with_named_skips(monkeypatch):
    from tradehub import fifteen_tracking as tracking
    from tests.test_fifteen_tracking import CaptureSupa, tape

    open_ = datetime(2026, 11, 13, 21, 15, tzinfo=UTC)  # a Friday window, 16:15 ET
    close = open_ + timedelta(minutes=15)
    halt_open = datetime(2026, 11, 13, 21, 45, tzinfo=UTC)  # frozen 16:50 ET
    targets = {"gold_15m": [
        {"target": "kalshi:GOLD-BUY", "cutoff_at": close.isoformat()},
        {"target": "kalshi:GOLD-HALT", "cutoff_at": (halt_open + timedelta(minutes=15)).isoformat()},
    ]}
    forecasts = {"gold_15m": [
        {"target": "kalshi:GOLD-BUY", "probability": 0.63, "frozen_at": "2026-11-13T21:20:00+00:00",
         "payload": {"yes_ask": 0.51, "yes_bid": 0.49}},
        {"target": "kalshi:GOLD-HALT", "probability": 0.90, "frozen_at": "2026-11-13T21:50:00+00:00",
         "payload": {"yes_ask": 0.50, "yes_bid": 0.48}},
    ]}
    monkeypatch.setattr(tracking, "fetch_targets",
                        lambda supa, family, since, until: targets.get(family, []))
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: forecasts.get(f, []))
    monkeypatch.setattr(tracking.store, "fetch_settlements", lambda supa, targets: {})
    supa = CaptureSupa()
    out = tracking.record_decisions(supa, datetime(2026, 11, 13, 22, 0, tzinfo=UTC),
                                    series_set=metals.SERIES, live_gate=False,
                                    candles_fn=lambda *a: tape())
    assert out["windows"] == 2 and out["buy"] == 1 and out["skip"] == 1
    rows = supa.tables["fifteen_rule_decisions"]
    buy = rows[("KXGOLD15M", "kalshi:GOLD-BUY")]
    assert buy["action"] == "buy" and buy["gate_version"] == "v1" and buy["side"] == "yes"
    halt = rows[("KXGOLD15M", "kalshi:GOLD-HALT")]
    assert halt["action"] == "skip" and halt["reason"] == "halt"
    # No oil rows were written by the metals pass.
    assert {r["series"] for r in rows.values()} == {"KXGOLD15M"}
