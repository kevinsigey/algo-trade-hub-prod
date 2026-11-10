"""Cron entrypoint: one Batch 2 candidate pass — generate debate
candidates from the RECORDED screening/guidance flow (screen entrants,
band zones off the latest completed snapshot, conjunctions), then drain
the queue into verdict renders against the shared daily debate budget.

Display data only — candidates and verdicts; no book or order hooks.
Suggested cadence: after the nightly valuation compute, so candidates
are generated against the fresh completed snapshot (deploy-side act).
"""

from __future__ import annotations

import sys

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore
from tradehub.valuation import candidates


def main() -> int:
    load_local_env()
    client = get_client()
    summary = candidates.generate_candidates(client)
    counts = summary["counts"]
    snap = summary["snapshot"] or {}
    print(f"debate candidates: snapshot #{snap.get('id')} — "
          f"{counts['total']} candidates ({counts['conjunctions']} "
          f"conjunctions, {counts['entrants']} entrants, "
          f"{counts['zone_names']} zone names), {counts['excluded']} "
          f"excluded, {summary['inserted']} newly queued")
    results = candidates.run_candidate_debates(client, DataStore())
    rendered = sum(1 for r in results if r["status"] == "rendered")
    void = sum(1 for r in results if r["status"] == "void")
    print(f"debate drain: {len(results)} attempted, {rendered} rendered, "
          f"{void} void")
    for r in results:
        if r["status"] not in ("rendered", "void"):
            print(f"  {r['ticker']}: {r['status']} — {r.get('reason')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
