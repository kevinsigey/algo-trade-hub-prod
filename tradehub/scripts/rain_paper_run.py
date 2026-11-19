"""Step 19 runner: score the rain paper rule and write the report
($TRADEHUB_RESEARCH_DIR/rain_paper.json).

    python -m tradehub.scripts.rain_paper_run

Reads weather_rain ens-v2.1's frozen rows and their settlements from the
journal, scores the preregistered rule in tradehub/research/rain_paper.py,
and reports the recent listings pace beside it. Read-only.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from tradehub.core.supabase_client import get_client
from tradehub.research.rain_paper import FORECASTER, VERSION, evaluate, listings_pace


def _all(client, table: str, columns: str, **filters) -> list[dict]:
    rows, start = [], 0
    while True:
        q = client.table(table).select(columns)
        for key, value in filters.items():
            q = q.eq(key, value)
        page = q.range(start, start + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        start += 1000


def main() -> None:
    client = get_client()
    outcomes = {r["target"]: r["outcome"]
                for r in _all(client, "journal_settlements", "target,outcome")}
    raw = _all(client, "journal_forecasts", "target,probability,payload,frozen_at",
               forecaster=FORECASTER, forecaster_version=VERSION)
    all_rows = [{"frozen_at": datetime.fromisoformat(r["frozen_at"])} for r in raw]
    settled = [{"frozen_at": datetime.fromisoformat(r["frozen_at"]),
                "probability": r["probability"], "payload": r["payload"],
                "outcome": outcomes[r["target"]]}
               for r in raw if r["target"] in outcomes]
    now = datetime.now(UTC)
    report = {"rule": evaluate(settled),
              "listings_pace": listings_pace(all_rows, days=14, now=now),
              "run_at": now.isoformat()}
    out = Path(os.environ.get("TRADEHUB_RESEARCH_DIR", "/cache/research")) / "rain_paper.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps(report, indent=2, default=str))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
