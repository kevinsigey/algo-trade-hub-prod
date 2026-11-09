"""Cron entrypoint: one valuation fact-sheet pass over every ticker with a
guidance record (Phase 0 of the valuation-bands system).

Display data only — no debate, judge, book, or order hooks. Runs on the VPS
deploy crontab; cadence is set when Phase 1 wires the watch (spec section 5:
new guidance and crossings first). Until then this is run on demand.
"""

from __future__ import annotations

import sys

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore
from tradehub.valuation.run import compute


def main() -> int:
    load_local_env()
    sheets = compute(get_client(), DataStore())
    banded = sum(1 for s in sheets if s["status"] == "banded")
    print(f"valuation pass: {len(sheets)} sheets, {banded} banded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
