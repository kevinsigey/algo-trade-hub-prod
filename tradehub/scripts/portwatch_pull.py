"""Daily PortWatch pull: refresh the chokepoint transit series the Oil
page reads (tradehub/geo/portwatch.py). The dataset updates weekly, so a
daily pull with the fetcher's retries is generous; a failed pull leaves
the last good file in place -- the reader stamps its as-of date either
way. Run by cron in the container:

    python -m tradehub.scripts.portwatch_pull
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from tradehub.geo import portwatch


def main() -> None:
    path = portwatch.store_path()
    prior: dict = {}
    if path.exists():
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- a corrupt cache is rebuilt, not fatal
            prior = {}
    try:
        inventory = portwatch.fetch_inventory()
    except portwatch.PortWatchError:
        inventory = portwatch.probe_inventory()
        print("grouped inventory failed; probed", len(inventory), "chokepoints")
    if not inventory:
        inventory = {pid: (entry or {}).get("name") or pid
                     for pid, entry in (prior.get("series") or {}).items()}
        if not inventory:
            inventory = dict(portwatch.KNOWN_NAMES)
        print("discovery failed; reusing", len(inventory), "known chokepoints")
    series, failed = {}, []
    for portid, name in sorted(inventory.items()):
        try:
            rows = portwatch.trim(portwatch.fetch_series(portid))
        except portwatch.PortWatchError:
            failed.append(portid)
            rows = ((prior.get("series") or {}).get(portid) or {}).get("rows") or []
        series[portid] = {"name": name, "rows": rows}
        print(f"{portid} {name}: {len(rows)} rows"
              + (f" (through {rows[-1]['date']})" if rows else ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pulled_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                "series": series}))
    print(f"portwatch_pull: wrote {path} ({len(series)} chokepoints, {len(failed)} failed)")


if __name__ == "__main__":
    main()
