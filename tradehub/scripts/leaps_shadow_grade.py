"""Cron entrypoint: the Spec F LEAPS shadow trial (idea 81) — one
nightly pass: intake consumes new qualifying Spec C crossings for T8
names, then grading refreshes marks and closes pairs on T8's falsifiers,
at expiry, or at trial end (tradehub/leaps_shadow.py has the frozen
rules). Shadow only: no orders, no path to them. Suggested cadence:
nightly, beside the valuation grade (deploy-side act).
"""

from __future__ import annotations

import sys

from tradehub import leaps_shadow
from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client


def main() -> int:
    load_local_env()
    client = get_client()
    intake = leaps_shadow.run_intake(client)
    grading = leaps_shadow.run_grading(client)
    print(f"leaps shadow: intake {intake}; grading {grading}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
