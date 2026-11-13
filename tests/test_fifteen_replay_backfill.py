"""A0 backfill support: the tape archive writes one JSON file per coin
per UTC day (atomically, re-runnable), and the daily archive window is
the trailing three days ending at today's UTC midnight -- always inside
Hyperliquid's ~3.5-day 1-minute retention."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from tradehub.scripts.fifteen_replay_archive import archive_window
from tradehub.scripts.fifteen_replay_backfill import write_tapes


def test_write_tapes_splits_by_coin_and_day(tmp_path):
    t0 = datetime(2026, 11, 11, 23, 59, tzinfo=UTC)
    tape = [(t0, 100.0), (t0 + timedelta(minutes=1), 100.5),
            (t0 + timedelta(minutes=2), 101.0)]
    written = write_tapes({"xyz:CL": tape, "xyz:GOLD": tape[:1]}, tmp_path)
    assert len(written) == 3  # CL spans two days, GOLD one
    day1 = json.loads((tmp_path / "xyz_CL-2026-11-11.json").read_text())
    day2 = json.loads((tmp_path / "xyz_CL-2026-11-12.json").read_text())
    assert day1 == [["2026-11-11T23:59:00+00:00", 100.0]]
    assert len(day2) == 2 and day2[0][1] == 100.5
    # re-running overwrites cleanly, no .tmp litter
    write_tapes({"xyz:CL": tape}, tmp_path)
    assert not list(tmp_path.glob("*.tmp"))


def test_archive_window_is_trailing_three_days_to_midnight():
    start, end = archive_window(datetime(2026, 11, 12, 17, 40, tzinfo=UTC))
    assert end == datetime(2026, 11, 12, tzinfo=UTC)
    assert start == datetime(2026, 11, 9, tzinfo=UTC)
