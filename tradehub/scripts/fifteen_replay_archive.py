"""Daily archive of the fifteen-minute replay + the underlyings' raw
1-minute tapes (Kevin, 2026-11-12: "build our own archive so we can
have our own backtest data").

Why this exists: Hyperliquid serves only the last ~3.5 days of 1-minute
candles, so any window not replayed within that span is gone for good
(the Aug-Nov backfill the v4 plan wanted is impossible after the fact).
This wrapper runs the A0 backfill for the trailing three days into the
persistent research dir -- the .done file makes overlap free -- and
dumps the raw tapes beside the replay rows, so future engines can be
re-run against the tape itself, not just today's replay of it.

    python -m tradehub.scripts.fifteen_replay_archive

Research dir: $TRADEHUB_RESEARCH_DIR or /cache/research. Rows land in
fifteen_replay_offsets.jsonl (the A0 dataset, accumulating), tapes in
tapes/<coin>-<YYYY-MM-DD>.json. Read-only against both APIs. Install as
a daily job (deploy crontab, ~06:07 UTC) once the A0 PR is live.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradehub.scripts.fifteen_replay_backfill import SERIES, run

ARCHIVE_DAYS = 3


def archive_window(today: datetime) -> tuple[datetime, datetime]:
    """[start, end) covering the trailing ARCHIVE_DAYS days up to today's
    UTC midnight -- always inside Hyperliquid's 1-minute retention, with
    a day's overlap so a missed run is recovered by the next one."""
    end = today.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=ARCHIVE_DAYS), end


def main(argv: list[str] | None = None) -> int:
    out = Path(os.environ.get("TRADEHUB_RESEARCH_DIR", "/cache/research"))
    start, end = archive_window(datetime.now(UTC))
    stats = run(out, start, end, series=SERIES, tape_out=out / "tapes")
    print({"archive": stats, "window": [start.isoformat(), end.isoformat()]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
