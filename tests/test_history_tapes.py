"""A0b tapes: Binance klines parse, HistData's EST-no-DST converts to UTC
at a fixed +5h (summer too), the cache never refetches, and the tape
comparison measures returns and level gaps on common minutes. No network."""
from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

from tradehub.backtest import history_tapes as ht


def _zip(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


def test_binance_klines_parse_with_and_without_header():
    body = "1794268800000,4145.28,4145.28,4142.88,4143.55,606.6,1794268859999,0,0,0,0,0\n"
    for text in ("open_time,open,high,low,close,volume,close_time,a,b,c,d,e\n" + body, body):
        assert ht.parse_binance_klines(_zip("x.csv", text)) == [
            (datetime.fromtimestamp(1794268800, UTC), 4143.55)]


def test_histdata_est_without_dst_is_utc_plus_five_all_year():
    text = "20240115 093000;2050.1;2051;2049;2050.5;0\n20240715 093000;2400;2401;2399;2400.25;0\n"
    rows = ht.parse_histdata(_zip("DAT_ASCII_XAUUSD_M1_2024.csv", text))
    # 09:30 EST is 14:30 UTC in January AND in July (no daylight saving).
    assert rows == [(datetime(2024, 1, 15, 14, 30, tzinfo=UTC), 2050.5),
                    (datetime(2024, 7, 15, 14, 30, tzinfo=UTC), 2400.25)]


def test_cache_fetches_once_and_does_not_cache_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(ht, "PAUSE_S", 0)
    calls = []
    p = tmp_path / "a" / "b.zip"
    assert ht._cached(p, lambda: calls.append(1)) is None and not p.exists()
    assert ht._cached(p, lambda: calls.append(1) or b"PK1") == b"PK1"
    assert ht._cached(p, lambda: calls.append(1) or b"other") == b"PK1"
    assert len(calls) == 2


def test_binance_tape_reads_cached_days_in_range(tmp_path, monkeypatch):
    def fail(url):
        raise AssertionError("network")
    monkeypatch.setattr(ht, "_binance_fetch", fail)
    t0 = datetime(2026, 11, 10, tzinfo=UTC)
    rows = "".join(f"{int((t0 + timedelta(minutes=m)).timestamp() * 1000)},0,0,0,{100 + m},0,0,0,0,0,0,0\n"
                   for m in range(3))
    day = tmp_path / "binance" / "XAUUSDT"
    day.mkdir(parents=True)
    (day / "2026-11-10.zip").write_bytes(_zip("k.csv", rows))
    tape = ht.binance_tape("XAUUSDT", t0 + timedelta(minutes=1), t0 + timedelta(minutes=3), tmp_path)
    assert tape == [(t0 + timedelta(minutes=1), 101.0), (t0 + timedelta(minutes=2), 102.0)]


def test_tape_compare_returns_and_gap():
    t0 = datetime(2026, 11, 10, tzinfo=UTC)
    a = [(t0 + timedelta(minutes=m), p) for m, p in enumerate([100, 101, 100.5, 102, 101])]
    b = [(t, p * 1.001) for t, p in a]  # same moves, 10 bp level basis
    out = ht.tape_compare(a, b)
    assert out["common_minutes"] == 5 and out["return_pairs"] == 4
    assert abs(out["return_corr"] - 1.0) < 1e-9
    assert abs(out["median_gap_bps"] - 9.99) < 0.01


def test_golden_identical_tapes_pass_and_outcomes_follow_the_rule():
    from tradehub.scripts.history_golden import series_golden
    t0 = datetime(2026, 11, 10, tzinfo=UTC)
    tape = [(t0 + timedelta(minutes=m), 100 * (1.0005 ** m)) for m in range(300)]
    close = t0 + timedelta(minutes=240)
    out = series_golden(tape, list(tape), {close: 1, close - timedelta(minutes=15): 0})
    assert out["a_within_1e5"] == 1.0 and out["b_within_0_01"] == 1.0
    # A rising tape settles YES: the first window agrees, the second (said NO) does not.
    assert out["outcome_agree"] == {"binance": 0.5, "hl": 0.5}
