"""Cron entrypoint: one Chokepoints snapshot for every configured region.

Run every 15 minutes by the VPS timer (vps-stack). Keyless feeds plus the AIS
consumer's state file; the FIRMS MAP_KEY comes from the environment when set.
"""

from __future__ import annotations

import json

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.geo.regions import REGIONS
from tradehub.geo.snapshot import run_snapshot


def main() -> int:
    load_local_env()
    supa = get_client()
    out = [run_snapshot(supa, region) for region in REGIONS.values()]
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
