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
    client = get_client()
    out = lw.run_tick(client)
    # Thesis tracker PR 6: the kill-line bridge rides the watcher
    # runner — sync theses.kill_lines into watches and open an
    # exit_review action for any kill-line fire. Fail-soft: a bridge
    # failure never takes the tick down with it.
    try:
        from tradehub.tracker import kill_lines
        bridge = kill_lines.run_bridge(client)
        sync, reviews = bridge["sync"], bridge["reviews"]
        if sync["armed"] or sync["disabled"] or reviews["actions_opened"]:
            print(f"kill-line bridge: {sync['armed']} armed, "
                  f"{sync['reenabled']} re-enabled, "
                  f"{sync['disabled']} disabled, "
                  f"{reviews['actions_opened']} exit reviews opened "
                  f"({reviews['fires_seen']} recent fires)")
    except Exception as exc:  # noqa: BLE001 -- named, never fatal
        print(f"kill-line bridge failed: {type(exc).__name__}: {exc}")
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
