"""Timer entrypoint: one Kalshi LIVE micro-pilot pass (issue #590).

Runs tradehub/kalshi_live_lane.py's run_once against Kevin's live
Kalshi account: reconcile open live rows, evaluate the pilot's gates,
then trade fresh RAW-rule buys on the three locked series at the
pilot's sizing. Refuses loudly (exit 1) whenever the live guard fails
-- a runner without KALSHI_LIVE_ENABLED=1, KALSHI_LIVE_ENV=live and
the production host places nothing. Ships with the enable flag unset;
Kevin sets it himself after reviewing the merged PR.

Installed on the VPS as a systemd timer on the same +2-minute offset
as the demo runner (the forecasts freeze on the 5-minute marks, so +2
trades the same window's freeze while it is still open). Real money:
the lane's own ceilings, daily stop, floor halt and gates are the
protection, all in tradehub/kalshi_live_lane.py.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from tradehub.core.env import load_local_env
from tradehub.core.kalshi_live_portfolio import KalshiLivePortfolio
from tradehub.core.supabase_client import get_client
from tradehub.kalshi_live_lane import run_once


def main() -> int:
    load_local_env()
    try:
        portfolio = KalshiLivePortfolio()
    except ValueError as exc:
        print(json.dumps({"kalshi_live": "refused", "reason": str(exc)}))
        return 1
    summary = run_once(get_client(), portfolio, datetime.now(UTC))
    print(json.dumps({"kalshi_live": summary}, default=str))
    return 1 if "refused" in summary else 0


if __name__ == "__main__":
    sys.exit(main())
