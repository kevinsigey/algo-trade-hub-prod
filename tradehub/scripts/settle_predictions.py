"""Cron entrypoint: settle open predictions against Kalshi market results.

Runs one settlement pass and refreshes each engine's track record, then
exits. Run hourly by the VPS `tradehub-settle.timer` — there is no
polling loop here. Simulated P&L wiring (spec section 4.5's fees+spread
term) lands with the paper-trading work; until then the gate receives
None and promotion stays blocked on that criterion.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone

from tradehub.core.env import load_local_env
from tradehub.core.kalshi_feed import fetch_market
from tradehub.core.supabase_client import complete_run, get_client, start_run
from tradehub.journal.legacy import journal_engines, journal_scores
from tradehub.settlement import run_settlement_pass
from tradehub.track_record import refresh_track_record

log = logging.getLogger(__name__)

# (engine, cadence) pairs the cron refreshes — the spec's engine set (section
# 3.1). Cadence sets the gate's contract minimum: daily engines need 200
# settled contracts, monthly-release engines 50. `engine` values must match
# what each engine writes into predictions.engine.
ENGINES = [
    ("gas", "daily"),
    ("cpi_nowcast", "monthly"),
    ("labor_nowcast", "monthly"),
    ("crypto", "daily"),
    ("sports_nfl", "daily"),
    ("sports_cfb", "daily"),
]


def _record(call) -> None:
    """Run recording must never crash the settle: the health marker is worth less than the pass."""
    try:
        call()
    except Exception:  # noqa: BLE001
        log.exception("settle run recording failed")


def main() -> int:
    # Entry point: load the developer-local `.env` explicitly. A no-op in
    # production, where the container supplies real variables and has no `.env`.
    # See `tradehub.core.env`.
    load_local_env()
    supa = get_client()
    # Every pass leaves a run row in scanner_runs (engines_run ["settle"]), so Health can say
    # when the settle JOB last ran -- `predictions.settled_at` cannot: it only moves when a
    # contract actually settles, so a healthy pass with nothing to settle read as a dead job.
    run_id = f"settle-{datetime.now(timezone.utc).isoformat()}"
    started = time.monotonic()
    _record(lambda: start_run(run_id, ["settle"], client=supa))
    try:
        summary = run_settlement_pass(supa, fetch_market)
        refreshed = []
        skipped = []
        # One ledger of record (v2 spec §4): an engine with a journal scorecard is graded by the journal, so
        # its legacy rollup is left alone. Its `predictions` rows are still settled above (the CPI display and
        # the sports hub calibration read them); only the second headline number is retired.
        on_journal = journal_engines(journal_scores(supa))
        for engine, cadence in ENGINES:
            if engine in on_journal:
                skipped.append(engine)
                continue
            payloads = refresh_track_record(supa, engine, cadence=cadence, simulated_pnl_after_fees=None)
            refreshed.extend(f"{engine}@{p['engine_version']}" for p in payloads)
        summary["track_record_refreshed"] = refreshed
        summary["track_record_skipped_on_journal"] = skipped
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _record(lambda: complete_run(run_id, 0, time.monotonic() - started, error, client=supa))
        raise
    _record(lambda: complete_run(run_id, summary.get("settled", 0), time.monotonic() - started,
                                 None, client=supa))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
