"""Score the fifteen-minute v4 shadow family off the forward offset
track and announce state transitions (preregistration:
docs/superpowers/specs/2026-11-14-fifteen-v4-shadow-family-prereg.md).

    python -m tradehub.scripts.fifteen_candidates_score

Read-only against fifteen_window_offsets and fifteen_min_ticks. The
only writes are gate_switch alerts in the watcher_alerts outbox when a
candidate first becomes promotion-eligible or is killed -- the writer
deduplicates on (version, event), so running this daily is the
intended cadence (a deploy crontab entry, like the other hub jobs,
once the PR is live). A kill is terminal: once a candidate's killed
alert exists it is not scored again and no later alert fires for it.
Eligibility is a notification and a decision request, never a switch:
promotion stays Kevin's word.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from tradehub import fifteen_candidates as fc
from tradehub.core.supabase_client import get_client
from tradehub.fifteen_tracking import _tick_buckets, fetch_ticks
from tradehub.gate_alerts import write_gate_alert
from tradehub.journal import store
from tradehub.oil_fifteen_rule import OFFSETS_TABLE

FAMILY = "fifteen"
ALERTS_TABLE = "watcher_alerts"


def _announce(client, result: dict) -> None:
    version = result["version"]
    if result["eligible"]:
        write_gate_alert(
            client, family=FAMILY, version=version, event="eligible",
            title=f"{version} is promotion-eligible",
            body=(f"{result['trades']} fresh trades since 2026-11-15: net "
                  f"{result['net_per_contract']} per contract, low95 "
                  f"{result['low95']}, paired low95 vs the live gate "
                  f"{result['paired_low95']}. Promotion still needs Kevin's "
                  "word -- this alert is the notification, not a switch."),
            evidence=result)
    elif result["killed"]:
        write_gate_alert(
            client, family=FAMILY, version=version, event="killed",
            title=f"{version} killed by its stopping rule",
            body=(f"{result['trades']} fresh trades over {result['days_run']} "
                  f"days without clearing the promotion bar (net "
                  f"{result['net_per_contract']} per contract, low95 "
                  f"{result['low95']}). Scoring stops; the record stays "
                  "readable."),
            evidence=result)


def _already_killed(client) -> set[str]:
    """Versions whose killed alert already exists. The kill is
    terminal (preregistration): those candidates are not scored again
    and no later 'eligible' alert may fire for them."""
    rows = store.select_all(
        client, ALERTS_TABLE,
        lambda q: q.eq("kind", "gate_switch").eq("family", FAMILY),
        ("id",))
    killed = set()
    for row in rows:
        ev = row.get("evidence") or {}
        if ev.get("event") == "killed" and ev.get("version"):
            killed.add(ev["version"])
    return killed


def _fills(client, rows: list[dict]) -> dict:
    """Ask sizes from the minute tape, keyed the way evaluate() looks
    them up: (series, close_time, offset) -> {"yes": size, "no": size},
    one tick per offset -- the one whose elapsed time sits closest to
    it, the forward record's own bucketing (_tick_buckets)."""
    closes: dict[str, set[str]] = {}
    for row in rows:
        closes.setdefault(row["series"], set()).add(str(row["close_time"]))
    fills: dict = {}
    for series, close_times in sorted(closes.items()):
        by_close: dict[str, list[dict]] = {}
        for tick in fetch_ticks(client, series, sorted(close_times)):
            by_close.setdefault(str(tick["close_time"]), []).append(tick)
        for close_time, ticks in by_close.items():
            for k, tick in _tick_buckets(ticks).items():
                fills[(series, close_time, k)] = {
                    "yes": tick.get("yes_ask_size"),
                    "no": tick.get("no_ask_size"),
                }
    return fills


def main(argv: list[str] | None = None) -> int:
    client = get_client()
    rows = store.select_all(
        client, OFFSETS_TABLE,
        lambda q: q.gte("close_time", fc.PREREG_AT.isoformat()),
        ("close_time", "series", "target", "offset_min"))
    fills = _fills(client, rows)
    killed_before = _already_killed(client)
    now = datetime.now(UTC)
    report = {"evaluated_at": now.isoformat(), "offset_rows": len(rows),
              "candidates": []}
    for version in fc.CANDIDATES:
        if version in killed_before:
            report["candidates"].append(
                {"version": version, "killed": True, "scored": False})
            continue
        result = fc.evaluate(rows, version, now=now, fills=fills)
        _announce(client, result)
        report["candidates"].append(result)
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
