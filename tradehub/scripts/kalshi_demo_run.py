"""Timer entrypoint: one Kalshi DEMO gas-runner pass (Kevin, 2026-11-12).

Runs tradehub/kalshi_demo.py's run_once against the Kalshi demo account:
reconcile open demo orders, then trade the live gate's fresh gated
natural-gas buys at 1% of the demo balance per decision. Refuses loudly
(exit 1) whenever the demo guard fails -- a runner pointed at anything
but demo-api.kalshi.co with KALSHI_ENV=demo places nothing.

Installed on the VPS as a systemd timer firing two minutes after each
5-minute fifteen_min decision pass (see the PR for the unit files and the
tradehub-job dispatcher case); the decisions it consumes land on the
5-minute marks, so +2 min trades the same cycle's freeze.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from tradehub.core.env import load_local_env
from tradehub.core.kalshi_portfolio import KalshiPortfolio
from tradehub.core.supabase_client import get_client
from tradehub.kalshi_demo import run_once


def main() -> int:
    load_local_env()
    try:
        portfolio = KalshiPortfolio()
    except ValueError as exc:
        print(json.dumps({"kalshi_demo": "refused", "reason": str(exc)}))
        return 1
    summary = run_once(get_client(), portfolio, datetime.now(UTC))
    print(json.dumps({"kalshi_demo": summary}, default=str))
    return 1 if "refused" in summary else 0


if __name__ == "__main__":
    sys.exit(main())
