"""The collector's cache restoration: a previous run's tape comes back
only when the file is really this symbol's cache. Anything else --
missing, corrupt, a non-mapping payload, another symbol -- restores
nothing rather than crashing the daemon or relabeling a foreign tape
(CodeRabbit on PR #544)."""

import json

from tradehub import binance_tape as tape
from tradehub.scripts.binance_ws_collect import _restored_klines


def _write(tmp_path, text):
    path = tmp_path / "xauusdt-1m.json"
    path.write_text(text)
    return str(path)


def test_missing_cache_restores_nothing(tmp_path):
    assert _restored_klines(str(tmp_path / "nope.json")) == {}


def test_valid_cache_restores_its_klines(tmp_path):
    path = _write(tmp_path, json.dumps(
        {"symbol": tape.SYMBOL, "written_at": "2026-11-16T15:00:00+00:00",
         "klines": [[1794843840000, 3871.43], [1794843900000, 3872.0]]}))
    assert _restored_klines(path) == {"1794843840000": 3871.43,
                                      "1794843900000": 3872.0}


def test_non_mapping_payloads_restore_nothing(tmp_path):
    assert _restored_klines(_write(tmp_path, "[]")) == {}
    assert _restored_klines(_write(tmp_path, "null")) == {}
    assert _restored_klines(_write(tmp_path, '"just a string"')) == {}


def test_another_symbols_cache_restores_nothing(tmp_path):
    path = _write(tmp_path, json.dumps(
        {"symbol": "ETHUSDT", "klines": [[1794843840000, 3000.0]]}))
    assert _restored_klines(path) == {}


def test_corrupt_cache_restores_nothing(tmp_path):
    assert _restored_klines(_write(tmp_path, "{not json")) == {}


# -- gap record + backoff (Claude's cleanup, 2026-11-17) ----------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from tradehub.scripts.binance_ws_collect import (  # noqa: E402
    _next_backoff, _note_gap, _restored_gaps, _sleep_seconds)


def test_note_gap_records_start_end_and_minutes(capsys):
    state = {"gaps": []}
    start = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    minutes = _note_gap(state, start, start + timedelta(minutes=7))
    assert minutes == 7.0
    assert state["gaps"] == [{"start": "2026-11-17T12:00:00+00:00",
                              "end": "2026-11-17T12:07:00+00:00"}]
    assert "gap" in capsys.readouterr().out  # the gap is said out loud


def test_note_gap_trims_to_the_cap():
    state = {"gaps": [{"start": "x", "end": "y"}] * 250}
    start = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
    _note_gap(state, start, start + timedelta(minutes=1))
    assert len(state["gaps"]) == 200
    assert state["gaps"][-1]["start"] == "2026-11-17T12:00:00+00:00"


def test_backoff_resets_only_after_a_stable_stream():
    assert _next_backoff(40, stable=True) == 5
    assert _next_backoff(5, stable=False) == 10
    assert _next_backoff(40, stable=False) == 60  # capped


def test_sleep_seconds_jitters_around_the_backoff():
    for _ in range(50):
        s = _sleep_seconds(20)
        assert 15.0 <= s <= 25.0


def test_restored_gaps_round_trip_through_the_cache_payload(tmp_path):
    path = tmp_path / "xauusdt-1m.json"
    state = {"symbol": tape.SYMBOL, "klines": {},
             "gaps": [{"start": "2026-11-17T12:00:00+00:00",
                       "end": "2026-11-17T12:07:00+00:00"}]}
    tape.write_cache(str(path), state, datetime(2026, 11, 17, 13, 0, tzinfo=UTC))
    assert _restored_gaps(str(path)) == state["gaps"]
    assert tape.read_gaps(path=str(path)) == state["gaps"]


def test_read_gaps_on_a_missing_or_foreign_cache_is_empty(tmp_path):
    assert tape.read_gaps(path=str(tmp_path / "nope.json")) == []
    path = _write(tmp_path, json.dumps({"symbol": "ETHUSDT", "gaps": [{"start": "a"}]}))
    assert _restored_gaps(path) == []
