"""The Binance tape cache (2026-11-16 transport amendment): the kline
fold, the Vision seed parse, the atomic write, and the strict reader
(missing/corrupt/stale raises -- an outage never masquerades as a
read), plus the shadow's record pass running on the cached tape.
"""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_fifteen_blend import FakeSupa, _patch
from tradehub import binance_tape as tape
from tradehub import fifteen_binance as fb

NOW = datetime(2026, 11, 16, 16, 0, tzinfo=UTC)


def _msg(minute: datetime, close: float, *, closed=True):
    return {"e": "kline", "k": {"t": int(minute.timestamp() * 1000),
                                "i": "1m", "c": str(close), "x": closed}}


# -- the fold -------------------------------------------------------------------


def test_apply_kline_keeps_only_final_closes():
    state = tape.empty_state()
    m = datetime(2026, 11, 16, 15, 59, tzinfo=UTC)
    # A provisional update (k.x false) never lands: it is not the
    # minute's close, and a dropped connection would freeze it in the
    # cache as if it were (CodeRabbit on PR #544).
    assert not tape.apply_kline(state, _msg(m, 4000.0, closed=False), NOW)
    assert state["klines"] == {}
    assert tape.apply_kline(state, _msg(m, 4001.5, closed=True), NOW)
    assert not tape.apply_kline(state, _msg(m, 4001.5, closed=True), NOW)
    assert state["klines"] == {str(int(m.timestamp() * 1000)): 4001.5}


def test_apply_kline_ignores_malformed_frames():
    state = tape.empty_state()
    assert not tape.apply_kline(state, {"k": {"t": "soon"}}, NOW)
    assert not tape.apply_kline(state, {"nope": 1}, NOW)
    assert state["klines"] == {}


def test_apply_kline_prunes_beyond_retention():
    state = tape.empty_state()
    old = NOW - tape.RETAIN - timedelta(minutes=1)
    tape.apply_kline(state, _msg(old, 1.0), NOW - tape.RETAIN)
    tape.apply_kline(state, _msg(NOW, 2.0), NOW)
    assert list(state["klines"].values()) == [2.0]


# -- the Vision seed --------------------------------------------------------------


def test_vision_rows_parse_and_skip_the_header():
    rows = [["open_time", "open", "high", "low", "close"],
            ["1794779100000", "4000", "4001", "3999", "4000.5"],
            ["garbage"]]
    assert tape.parse_vision_rows(rows) == [(1794779100000, 4000.5)]


def test_seed_never_overwrites_a_streamed_minute():
    state = tape.empty_state()
    tape.apply_kline(state, _msg(NOW, 4002.0), NOW)
    added = tape.seed(state, [(int(NOW.timestamp() * 1000), 3999.0),
                              (int(NOW.timestamp() * 1000) - 60000, 3998.0)])
    assert added == 1
    assert state["klines"][str(int(NOW.timestamp() * 1000))] == 4002.0


# -- the reader -------------------------------------------------------------------


def _write(tmp_path, state, now=NOW):
    path = str(tmp_path / "xauusdt-1m.json")
    tape.write_cache(path, state, now)
    return path


def test_read_round_trip_and_range_convention(tmp_path):
    state = tape.empty_state()
    start = NOW - timedelta(minutes=10)
    for i in range(11):
        tape.apply_kline(state, _msg(start + timedelta(minutes=i),
                                     4000.0 + i), NOW)
    path = _write(tmp_path, state)
    out = tape.read_cached_klines("XAUUSDT", start + timedelta(minutes=2),
                                  start + timedelta(minutes=5),
                                  path=path, now=NOW)
    assert [c for _, c in out] == [4002.0, 4003.0, 4004.0]  # [start, end)
    assert out[0][0] == start + timedelta(minutes=2)


def test_read_raises_on_missing_corrupt_and_wrong_symbol(tmp_path):
    with pytest.raises(RuntimeError, match="unavailable"):
        tape.read_cached_klines("XAUUSDT", NOW, NOW + timedelta(minutes=1),
                                path=str(tmp_path / "nope.json"), now=NOW)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(RuntimeError, match="unavailable"):
        tape.read_cached_klines("XAUUSDT", NOW, NOW + timedelta(minutes=1),
                                path=str(bad), now=NOW)
    with pytest.raises(RuntimeError, match="holds XAUUSDT"):
        tape.read_cached_klines("XAGUSDT", NOW, NOW + timedelta(minutes=1),
                                path=str(bad), now=NOW)


def test_read_raises_on_a_stale_cache(tmp_path):
    state = tape.empty_state()
    tape.apply_kline(state, _msg(NOW - timedelta(hours=2), 4000.0), NOW)
    path = _write(tmp_path, state)
    with pytest.raises(RuntimeError, match="stale"):
        tape.read_cached_klines("XAUUSDT", NOW - timedelta(minutes=30),
                                NOW, path=path, now=NOW)


# -- the shadow on the cached tape --------------------------------------------------

CLOSE = datetime(2026, 11, 16, 15, 30, tzinfo=UTC)
OPEN = CLOSE - timedelta(minutes=15)
TARGET = "kalshi:KXGOLD15M-26NOV161030-30"


def test_record_pass_reads_the_cache_by_default(tmp_path, monkeypatch):
    cal = {"target": TARGET, "cutoff_at": CLOSE.isoformat()}
    fcs = [{"target": TARGET, "probability": 0.50,
            "frozen_at": (OPEN + timedelta(minutes=5)).isoformat(),
            "payload": {"yes_ask": 0.51, "yes_bid": 0.49}}]
    _patch(monkeypatch, calendars={"gold_15m": [cal]},
           forecasts={"gold_15m": fcs}, settlements={TARGET: 1})
    state = tape.empty_state()
    start = OPEN - fb.TAPE_SPAN - timedelta(minutes=5)
    for i in range(200):
        tape.apply_kline(state, _msg(
            start + timedelta(minutes=i),
            4000.0 * math.exp(0.0003 * i)), NOW)
    path = _write(tmp_path, state, now=NOW)
    monkeypatch.setenv("BINANCE_TAPE_CACHE", path)
    supa = FakeSupa()
    out = fb.record_binance(supa, NOW)
    assert out["windows"] == 1
    rows = supa.tables.get(fb.DECISIONS_TABLE, [])
    assert len(rows) == 1
    assert rows[0]["gate_version"] == fb.SHADOW_VERSION
    # The read must have SUCCEEDED: a stale tape writes a skip row with
    # the same gate version, and these assertions are what tell the two
    # apart (CodeRabbit on PR #544).
    assert rows[0]["model_prob"] is not None and rows[0]["sigma_1m"] is not None
    assert rows[0]["reason"] != "stale_tape"
