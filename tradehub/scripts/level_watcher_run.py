"""Cron entrypoint: one Level Watcher tick (Spec D, Stage 1 — Rung 1).

Evaluates armed watches against Alpaca 1-min bars + latest trade,
writes heartbeats during market hours, drives Spec C's band-crossing
state machine at intraday prices when a band watch is armed, and
records fires + alerts. STAGE 1 IS ALERT-ONLY: this places nothing —
there is no order path in the watcher. Suggested cadence (deploy
crontab): every minute on weekdays; the tick exits fast outside
market hours (09:30–16:00 ET) and heartbeats only inside them.
"""

from __future__ import annotations

import sys

from tradehub import level_watcher as lw
from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client


def main() -> int:
    load_local_env()
    out = lw.run_tick(get_client())
    if not out["market_hours"]:
        print("level watcher: outside market hours — idle")
        return 0
    print(f"level watcher tick: {len(out['fired'])} fired, "
          f"{len(out['evaluated'])} evaluated, "
          f"{len(out['suppressed'])} suppressed, "
          f"heartbeat {'written' if out['heartbeat'] else 'fresh'}, "
          f"down alert {'written' if out['down_alert'] else 'no'}, "
          f"band {out['band']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
