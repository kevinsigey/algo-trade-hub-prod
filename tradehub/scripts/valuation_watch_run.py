"""Cron entrypoint: one section-5 cadence pass — refresh the fact sheets,
run the band watch (held-position flags + event triggers), then drain the
trigger queue into verdict renders against the shared daily debate budget.

Display data only — flags and verdicts; no book or order hooks. Runs on the
VPS deploy crontab beside valuation_bands_run; suggested cadence is hourly
while the market is open (deploy-side act, noted in the Phase 1 report).
"""

from __future__ import annotations

import sys

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore
from tradehub.valuation import run as val_run
from tradehub.valuation import watch


def main() -> int:
    load_local_env()
    client, ds = get_client(), DataStore()
    sheets = val_run.compute(client, ds)
    banded = sum(1 for s in sheets if s["status"] == "banded")
    out = watch.compute_watch(client, ds)
    rendered = watch.drain_triggers(client, ds)
    sells = sum(1 for f in out["flags"] if f["flag"] == "potential_sell")
    print(f"valuation watch: {len(sheets)} sheets ({banded} banded), "
          f"{len(out['flags'])} held flags ({sells} potential-sell), "
          f"{out['triggers_queued']} triggers queued, "
          f"{len(rendered)} verdicts rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
