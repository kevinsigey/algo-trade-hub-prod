"""Hourly precompute of the slow read-only pages (step 5, Nov 12).

The journal job already runs hourly and already pays the Health build
for its failure notifier; this pass additionally persists that report
plus the Macro and Weather compositions as snapshots
(tradehub/snapshots.py), and /api/health, /api/macro, /api/weather and
/api/weather/map serve the snapshot while it is fresh (under 90
minutes), falling back to the live build otherwise.

Every snapshot is independent and fail-soft: one failing build records
its failure and never blocks the others or the journal run. A degraded
Macro build (a source read failed) is NOT snapshotted -- the endpoint's
own rule for its cache, kept: a partial payload must not be served as
if it were whole for up to an hour.
"""

from __future__ import annotations

from datetime import datetime

from tradehub import snapshots
from tradehub.health import collect_health


def write_all(supa, now: datetime, *, health_report: dict | None = None) -> dict[str, str]:
    """Build and persist every snapshot; returns per-name status."""
    statuses: dict[str, str] = {}

    try:
        report = health_report if health_report is not None else collect_health(supa, now=now)
        snapshots.write_snapshot("health", report, now=now)
        statuses["health"] = "written"
    except Exception as exc:  # noqa: BLE001 -- one build never blocks the rest
        statuses["health"] = f"failed: {exc}"[:200]

    try:
        from tradehub.macro import compose_macro
        payload, degraded = compose_macro(supa)
        if degraded:
            statuses["macro"] = "degraded, not snapshotted"
        else:
            snapshots.write_snapshot("macro", payload, now=now)
            statuses["macro"] = "written"
    except Exception as exc:  # noqa: BLE001
        statuses["macro"] = f"failed: {exc}"[:200]

    try:
        from tradehub.weather_page import build_weather
        snapshots.write_snapshot("weather", build_weather(supa), now=now)
        statuses["weather"] = "written"
    except Exception as exc:  # noqa: BLE001
        statuses["weather"] = f"failed: {exc}"[:200]

    try:
        from tradehub.weather_map import compose_weather_map
        snapshots.write_snapshot("weather_map", compose_weather_map(supa), now=now)
        statuses["weather_map"] = "written"
    except Exception as exc:  # noqa: BLE001
        statuses["weather_map"] = f"failed: {exc}"[:200]

    return statuses
