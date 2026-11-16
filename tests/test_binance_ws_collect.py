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
