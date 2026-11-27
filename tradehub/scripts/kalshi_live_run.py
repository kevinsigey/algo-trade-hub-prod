"""Timer entrypoint: the Kalshi LIVE micro-pilot lane (issue #590).

Runs tradehub/kalshi_live_lane.py's run_once against Kevin's live
Kalshi account: reconcile open live rows, evaluate the pilot's gates,
then trade fresh RAW-rule buys on the three locked series at the
pilot's sizing. Refuses loudly (exit 1) whenever the live guard fails
-- a runner without KALSHI_LIVE_ENABLED=1, KALSHI_LIVE_ENV=live and
the production host places nothing. Ships with the enable flag unset;
Kevin sets it himself after reviewing the merged PR.

Execution amendment (2026-11-25, issue #619): the freeze->send gap of
the old 5-minute cadence (46-55s on the Nov 25 unfilleds) lost the
race on a moving tape, so the installed cron now runs this entrypoint
every minute with `--loop 55 --interval 8`: passes repeat inside the
minute and a frozen decision is sent within seconds of landing. Each
pass still records latency_s on its rows, so the improvement is
measured by the same field that exposed the problem. A pass that
raises is printed and the loop carries on; a guard refusal still
exits 1 at once.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime

from tradehub.core.env import load_local_env
from tradehub.core.kalshi_live_portfolio import KalshiLivePortfolio
from tradehub.core.supabase_client import get_client
from tradehub.kalshi_live_lane import run_once


def _arg_value(flag: str) -> float | None:
    if flag not in sys.argv:
        return None
    try:
        return float(sys.argv[sys.argv.index(flag) + 1])
    except (IndexError, ValueError):
        return None


def main() -> int:
    load_local_env()
    try:
        portfolio = KalshiLivePortfolio()
    except ValueError as exc:
        print(json.dumps({"kalshi_live": "refused", "reason": str(exc)}))
        return 1
    supa = get_client()
    loop_s = _arg_value("--loop") or 0.0
    interval = _arg_value("--interval") or 8.0
    started = time.monotonic()
    while True:
        try:
            summary = run_once(supa, portfolio, datetime.now(UTC))
        except Exception as exc:  # noqa: BLE001 -- one bad pass must not kill the loop
            summary = {"errors": [f"pass raised: {exc}"]}
        print(json.dumps({"kalshi_live": summary}, default=str), flush=True)
        if "refused" in summary:
            return 1
        if loop_s <= 0 or time.monotonic() - started + interval >= loop_s:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
