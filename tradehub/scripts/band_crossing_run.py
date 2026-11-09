"""Cron entrypoint: one band-crossing scan (Spec C, log-only build).

--mode weekly: the Monday scan on the closes stored on the latest fact
sheets. --mode auto: the event re-scan — runs only when the sheets have
advanced past the last completed scan's watermark (a re-banding), so a
new guide is reflected within the hour, hence within a day. The first
scan ever (empty state) is the baseline and establishes state silently.

LOG-ONLY: this records would-be actions in band_crossings. There is no
order path in the engine; nothing here can place, size, or route an
order. Suggested cadence (deploy crontab): weekly Mon 13:00 UTC, auto
hourly weekdays 13-21 UTC at :37 (after the :07 valuation watch).
"""

from __future__ import annotations

import argparse
import sys

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.valuation import band_crossing as bc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("weekly", "auto"), default="weekly")
    args = ap.parse_args()
    load_local_env()
    client = get_client()
    if args.mode == "auto":
        run, why = bc.auto_decision(client)
        if not run:
            print(f"band crossing auto-scan: skipped — {why}")
            return 0
        print(f"band crossing auto-scan: running — {why}")
        out = bc.run_scan(client, kind="event")
    else:
        out = bc.run_scan(client, kind="weekly")
    print(f"band crossing scan ({out['kind']}, mode {out['mode']}): "
          f"{out['banded_names']} banded names, {out['state_rows']} state "
          f"rows, {out['crossings_written']} crossings written, "
          f"{len(out['skipped'])} skipped, "
          f"{len(out['book_skips'])} book skips")
    return 0


if __name__ == "__main__":
    sys.exit(main())
