"""The Binance-tape gold shadow (preregistration
docs/superpowers/specs/2026-11-14-fifteen-binance-gold-shadow-prereg.md):
the klines fetch (parse + pagination), the record pass (the model's own
read at v1's freeze instant on the Binance tape, the live rule's own
evaluate on v1's frozen quotes, honest skips, the preregistration
filter), fresh-only scoring paired against the live rule's gold
decisions, and the fail-soft runner hook. No network: the tape fetch is
injected everywhere.
"""
import math
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_fifteen_blend import FakeSupa, _patch
from tradehub import fifteen_binance as fb
from tradehub import oil_fifteen_rule as rule
from tradehub.scripts import fifteen_min_run

# Monday Nov 16, 2026, 15:30Z close = 10:30 ET: futures open, no halt,
# and after PREREG_AT (2026-11-16T00:00Z).
CLOSE = datetime(2026, 11, 16, 15, 30, tzinfo=UTC)
OPEN = CLOSE - timedelta(minutes=15)
FROZEN = (OPEN + timedelta(minutes=5)).isoformat()
TARGET = "kalshi:KXGOLD15M-26NOV161030-30"
NOW = datetime(2026, 11, 16, 16, 0, tzinfo=UTC)


def _tape(start: datetime, minutes: int, *, drift=0.0003, base=4000.0):
    return [(start + timedelta(minutes=i), base * math.exp(drift * i))
            for i in range(minutes)]


def _world(*, prob=0.50, outcome=1, with_forecast=True, close=CLOSE, target=TARGET):
    cal = {"target": target, "cutoff_at": close.isoformat()}
    fcs = [{"target": target, "probability": prob, "frozen_at": FROZEN,
            "payload": {"yes_ask": 0.51, "yes_bid": 0.49}}] if with_forecast else []
    settled = {target: outcome} if outcome is not None else {}
    return {"gold_15m": [cal]}, {"gold_15m": fcs}, settled


def _use(monkeypatch, world):
    calendars, forecasts, settlements = world
    _patch(monkeypatch, calendars=calendars, forecasts=forecasts,
           settlements=settlements)


def _rows(supa):
    return supa.tables.get(fb.DECISIONS_TABLE, [])


# -- the klines fetch ---------------------------------------------------------

def _kline(t: datetime, close: float):
    return [int(t.timestamp() * 1000), str(close), str(close), str(close),
            str(close), "1.0", int(t.timestamp() * 1000) + 59999]


def test_klines_parse_and_paginate():
    start = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=1601)
    calls = []

    def fake_get(_url, params):
        calls.append(params)
        first = datetime.fromtimestamp(params["startTime"] / 1000, UTC)
        base = int((first - start).total_seconds() // 60)
        n = min(fb._KLINE_LIMIT, int((end - first).total_seconds() // 60))
        return [_kline(first + timedelta(minutes=i), 4000.0 + base + i)
                for i in range(n)]

    tape = fb.binance_klines("XAUUSDT", start, end, get_json=fake_get)
    assert len(calls) == 2  # 1500-candle cap, then the remainder
    assert calls[1]["startTime"] == int(
        (start + timedelta(minutes=1500)).timestamp() * 1000)
    assert len(tape) == 1601
    assert tape[0] == (start, 4000.0) and tape[-1][1] == 4000.0 + 1600


def test_klines_single_page_and_empty():
    start = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    tape = fb.binance_klines(
        "XAUUSDT", start, end,
        get_json=lambda _u, _p: [_kline(start + timedelta(minutes=i), 1.5)
                                 for i in range(10)])
    assert len(tape) == 10 and tape[3][1] == 1.5
    assert fb.binance_klines("XAUUSDT", start, end,
                             get_json=lambda _u, _p: []) == []


# -- the record pass ----------------------------------------------------------

def test_record_buy_row_from_the_binance_read(monkeypatch):
    _use(monkeypatch, _world(prob=0.50))
    supa = FakeSupa()
    seen = {}

    def klines(symbol, start, end):
        seen.update(symbol=symbol, start=start, end=end)
        return _tape(OPEN - timedelta(minutes=165), 200)

    out = fb.record_binance(supa, NOW, klines_fn=klines)
    assert out == {"windows": 1, "buy": 1}
    assert seen["symbol"] == "XAUUSDT" and seen["start"] <= OPEN - fb.TAPE_SPAN
    (row,) = _rows(supa)
    assert row["gate_version"] == "v5-binance-gold-shadow"
    assert row["series"] == "KXGOLD15M" and row["target"] == TARGET
    # The Binance tape drifts up hard: the shadow buys YES at v1's frozen
    # ask even though v1's own probability was a coin flip.
    assert row["action"] == "buy" and row["side"] == "yes" and row["cost"] == 0.51
    assert row["model_prob"] > 0.9 and row["v1_prob"] == 0.5
    assert row["market_prob"] == 0.5 and row["sigma_1m"] is not None
    assert row["session"] == "open" and row["outcome"] == 1
    assert row["pnl"] == rule.pnl("yes", 0.51, 1)


def test_record_follows_the_binance_prob_not_v1s(monkeypatch):
    _use(monkeypatch, _world(prob=0.99))  # v1 loved it; the Binance tape is flat
    supa = FakeSupa()
    flat = _tape(OPEN - timedelta(minutes=165), 200, drift=0.0)
    out = fb.record_binance(supa, NOW, klines_fn=lambda *_a: flat)
    (row,) = _rows(supa)
    assert out["buy"] == 0
    assert row["action"] == "skip" and row["reason"] == "no_edge"
    assert row["model_prob"] == 0.5 and row["v1_prob"] == 0.99


def test_record_stale_tape_is_an_honest_skip(monkeypatch):
    _use(monkeypatch, _world())
    supa = FakeSupa()
    short = _tape(OPEN - timedelta(minutes=165), 150)  # ends 15 min before the freeze
    fb.record_binance(supa, NOW, klines_fn=lambda *_a: short)
    (row,) = _rows(supa)
    assert row["action"] == "skip" and row["reason"] == "stale_tape"
    assert row["model_prob"] is None and row["frozen_at"] == FROZEN


def test_record_no_prediction_skip(monkeypatch):
    _use(monkeypatch, _world(with_forecast=False))
    supa = FakeSupa()
    fb.record_binance(supa, NOW, klines_fn=lambda *_a: _tape(OPEN, 60))
    (row,) = _rows(supa)
    assert row["action"] == "skip" and row["reason"] == "no_prediction"
    assert row["frozen_at"] is None and row["v1_prob"] is None


def test_windows_before_the_preregistration_are_never_written(monkeypatch):
    early_close = datetime(2026, 11, 15, 15, 30, tzinfo=UTC)  # Sunday, pre-PREREG_AT
    early_target = "kalshi:KXGOLD15M-26NOV151030-30"
    _use(monkeypatch, _world(close=early_close, target=early_target))
    supa = FakeSupa()
    out = fb.record_binance(supa, NOW, klines_fn=lambda *_a: _tape(OPEN, 60))
    assert out == {"windows": 0, "buy": 0} and _rows(supa) == []


# -- scoring ------------------------------------------------------------------

def _seed_eval(supa):
    def row(target, pnl):
        return {"series": "KXGOLD15M", "target": target,
                "window_open": "2026-11-16T15:15:00+00:00",
                "action": "buy" if pnl is not None else "skip",
                "outcome": 1, "pnl": pnl}
    supa.tables[fb.DECISIONS_TABLE] = [
        row("kalshi:A", 0.40), row("kalshi:B", 0.40), row("kalshi:C", -0.20),
        row("kalshi:D", 0.10)]  # D has no live-rule row: excluded from pairing
    supa.tables[rule.DECISIONS_TABLE] = [
        row("kalshi:A", 0.10), row("kalshi:B", -0.10), row("kalshi:C", -0.20)]


def test_evaluate_pairs_against_the_live_rules_gold_rows():
    supa = FakeSupa()
    _seed_eval(supa)
    ev = fb._evaluate(supa)
    assert ev["trades"] == 4 and ev["paired_windows"] == 3
    assert ev["paired_delta"] == round((0.30 + 0.50 + 0.0) / 3, 4)
    assert ev["criterion_met"] is False  # n far under the 100-trade bar
    assert ev["eligible"] is False


def test_evaluate_daily_writes_once_a_day():
    supa = FakeSupa()
    _seed_eval(supa)
    ev = fb.evaluate_daily(supa, NOW)
    assert ev["trades"] == 4 and len(supa.tables[fb.EVALS_TABLE]) == 1
    assert fb.evaluate_daily(supa, NOW) == {"skipped": "already_evaluated_today"}
    assert len(supa.tables[fb.EVALS_TABLE]) == 1
    assert fb.summary(supa)["promotion"]["path_built"] is False


class _RecordingSupa(FakeSupa):
    """FakeSupa that logs the target table of every write, so a test can
    fail on the side effect itself rather than on a status flag."""

    def __init__(self):
        super().__init__()
        self.writes = []

    def table(self, name):
        query = super().table(name)
        execute = query.execute

        def recording_execute():
            if query.mode in ("upsert", "insert"):
                self.writes.append(name)
            return execute()

        query.execute = recording_execute
        return query


def test_no_promotion_writes_anywhere(monkeypatch):
    # The preregistration builds no promotion path: across a full cycle
    # (record, daily evaluation, summary) the shadow may write only its
    # own two tables. Any future promotion write fails this test even if
    # summary's path_built flag were left at its literal False.
    _use(monkeypatch, _world())
    supa = _RecordingSupa()
    tape = _tape(OPEN - timedelta(minutes=165), 200)
    out = fb.record_binance(supa, NOW, klines_fn=lambda *_a: tape)
    assert out == {"windows": 1, "buy": 1}  # the cycle really ran
    fb.evaluate_daily(supa, NOW)
    fb.summary(supa)
    assert set(supa.writes) == {fb.DECISIONS_TABLE, fb.EVALS_TABLE}


# -- the runner hook ----------------------------------------------------------

def test_runner_hook_is_fail_soft(monkeypatch):
    def boom(_s, _n):
        raise RuntimeError("binance exploded")
    monkeypatch.setattr(fifteen_min_run.fifteen_binance, "record_binance", boom)
    monkeypatch.setattr(fifteen_min_run.fifteen_binance, "evaluate_daily", boom)
    ok = {"ran": True}
    for mod, fn in ((fifteen_min_run.fifteen_tracking, "record_decisions"),
                    (fifteen_min_run.fifteen_tracking, "record_offsets"),
                    (fifteen_min_run.fifteen_blend, "record_blend"),
                    (fifteen_min_run.fifteen_blend, "evaluate_daily"),
                    (fifteen_min_run.fifteen_volregime, "record_volregime"),
                    (fifteen_min_run.fifteen_volregime, "evaluate_daily")):
        monkeypatch.setattr(mod, fn, lambda *_a, **_k: ok)
    summary = fifteen_min_run.run(object(), [], NOW)
    assert "binance exploded" in summary["fifteen_binance"]["error"]
    assert "binance exploded" in summary["fifteen_binance_eval"]["error"]
    assert summary["fifteen_blend"] == ok and summary["fifteen_decisions"] == ok


# -- the prereg stopping rule + eval gap report (Claude's cleanup) -----------

def _settled_buy(i: int) -> dict:
    return {"series": fb.SERIES, "target": f"kalshi:T{i}",
            "window_open": "2026-11-16T15:15:00+00:00",
            "action": "buy", "outcome": 1, "pnl": 0.10}


def test_record_stops_at_300_fresh_trades(monkeypatch):
    supa = FakeSupa()
    supa.tables[fb.DECISIONS_TABLE] = [_settled_buy(i) for i in range(300)]
    _use(monkeypatch, _world())
    out = fb.record_binance(supa, NOW, klines_fn=lambda *_a: _tape(OPEN, 60))
    assert out == {"windows": 0, "buy": 0, "stopped": "fresh_trade_stop_300"}
    assert len(_rows(supa)) == 300  # nothing new was written


def test_record_still_runs_at_299_fresh_trades(monkeypatch):
    supa = FakeSupa()
    supa.tables[fb.DECISIONS_TABLE] = [_settled_buy(i) for i in range(299)]
    _use(monkeypatch, _world())
    out = fb.record_binance(supa, NOW, klines_fn=lambda *_a: _tape(OPEN, 60))
    assert "stopped" not in out


def test_a_failed_decisions_read_fails_closed(monkeypatch):
    # Claude's review: _stopped must not read through blend._read, which
    # swallows a failed read to [] -- that counts 0 trades and the
    # stopping rule fails open, so the shadow would keep recording past
    # its stop on a broken read. The read now raises, record_binance
    # propagates it, and the runner's fail-soft wrapper writes nothing.
    def boom(*_a, **_k):
        raise RuntimeError("decisions read failed")
    monkeypatch.setattr(fb.store, "select_all", boom)
    supa = FakeSupa()
    with pytest.raises(RuntimeError, match="decisions read failed"):
        fb.record_binance(supa, NOW, klines_fn=lambda *_a: _tape(OPEN, 60))
    assert _rows(supa) == []


def test_record_stops_at_the_prereg_date():
    supa = FakeSupa()
    out = fb.record_binance(supa, datetime(2027, 1, 15, tzinfo=UTC),
                            klines_fn=lambda *_a: _tape(OPEN, 60))
    assert out == {"windows": 0, "buy": 0, "stopped": "date_stop_2027-01-15"}


def test_eval_reports_the_collectors_tape_gaps(monkeypatch):
    supa = FakeSupa()
    _seed_eval(supa)
    monkeypatch.setattr(fb.binance_tape, "read_gaps", lambda: [
        {"start": "2026-11-17T12:00:00+00:00", "end": "2026-11-17T12:10:00+00:00"},
        {"start": "2026-11-17T13:00:00+00:00", "end": "2026-11-17T13:05:30+00:00"}])
    ev = fb._evaluate(supa)
    assert ev["tape_gaps"] == {"count": 2, "minutes": 15.5}
    assert fb.summary(supa)["tape_gaps"] == {"count": 2, "minutes": 15.5}
