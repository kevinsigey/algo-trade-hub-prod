"""Build the degree-day demand snapshot (phase-2 §5.3).

Run weekly (or by hand): fetches Open-Meteo archive temperatures for the Census
divisions' representative cities, computes the panel, and writes the snapshot JSON
the Weather page's panel serves. Usage: python -m tradehub.scripts.degree_days
"""

from __future__ import annotations

import json

from tradehub.weather_demand import build_snapshot, snapshot_path


def main() -> int:
    panel = build_snapshot()
    path = snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(panel), encoding="utf-8")
    nat = panel["national"]
    print(f"degree-days through {panel['week_end']}: national HDD {nat['hdd']} "
          f"(anomaly {nat['hdd_anomaly']}), CDD {nat['cdd']} (anomaly {nat['cdd_anomaly']}), "
          f"{nat['population_covered_pct']}% of population covered -> {path}")
    if panel["missing_regions"]:
        print(f"missing regions: {', '.join(panel['missing_regions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
