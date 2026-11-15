"""Scheduled-release calendar for the 15-minute study (Step A).

Hand-kept from the published schedules, as the plan specifies: the weekly
EIA / API releases are weekday-and-time rules; CPI, the Employment
Situation and FOMC decisions/minutes are explicit 2026 dates taken from
the BLS schedule of releases and the Federal Reserve meeting calendar
(both published a year ahead and verified 2026-11-14).

Known limits, stated rather than hidden:
- EIA petroleum status moves from Wednesday to Thursday on federal
  holiday weeks, and the API report shifts with it; the rule below keeps
  the regular weekday. A window flagged by the rule in a holiday week can
  be off by a day; the flag is a study feature, not a trading input.
- A government shutdown can delay BLS releases (it did in late 2025);
  the dates here are the SCHEDULED ones, which is what a no-look-ahead
  feature may use: the schedule is public before the window opens.

All times are America/New_York. A release is an instant; the study flags
windows whose entry falls within +/-15 minutes of one.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# Weekly rules: kind -> (weekday Mon=0, ET time, series it moves)
WEEKLY: dict[str, tuple[int, time, frozenset[str]]] = {
    "api_inventories": (1, time(16, 30), frozenset({"KXWTI15M", "KXBRENT15M"})),   # Tue
    "eia_petroleum": (2, time(10, 30), frozenset({"KXWTI15M", "KXBRENT15M"})),     # Wed
    "eia_gas_storage": (3, time(10, 30), frozenset({"KXNATGAS15M"})),              # Thu
}

_METALS = frozenset({"KXGOLD15M", "KXSILVER15M", "KXCOPPER15M"})

# BLS 2026 release dates (08:30 ET), from the BLS schedule of releases.
CPI_2026 = [date(2026, 1, 13), date(2026, 2, 11), date(2026, 3, 11),
            date(2026, 4, 10), date(2026, 5, 12), date(2026, 6, 10),
            date(2026, 7, 14), date(2026, 8, 12), date(2026, 9, 11),
            date(2026, 10, 14), date(2026, 11, 10), date(2026, 12, 10)]
JOBS_2026 = [date(2026, 1, 9), date(2026, 2, 6), date(2026, 3, 6),
             date(2026, 4, 3), date(2026, 5, 8), date(2026, 6, 5),
             date(2026, 7, 2), date(2026, 8, 7), date(2026, 9, 4),
             date(2026, 10, 2), date(2026, 11, 6), date(2026, 12, 4)]
# FOMC decision days 2026 (second day of each meeting, 14:00 ET) and the
# minutes releases (three weeks later, 14:00 ET), Federal Reserve calendar.
FOMC_DECISION_2026 = [date(2026, 1, 28), date(2026, 3, 18), date(2026, 4, 29),
                      date(2026, 6, 17), date(2026, 7, 29), date(2026, 9, 16),
                      date(2026, 10, 28), date(2026, 12, 9)]
FOMC_MINUTES_2026 = [date(2026, 2, 18), date(2026, 4, 8), date(2026, 5, 20),
                     date(2026, 7, 8), date(2026, 8, 19), date(2026, 10, 7),
                     date(2026, 11, 18), date(2026, 12, 30)]

DATED: dict[str, tuple[list[date], time, frozenset[str]]] = {
    "cpi": (CPI_2026, time(8, 30), _METALS),
    "jobs": (JOBS_2026, time(8, 30), _METALS),
    "fomc_decision": (FOMC_DECISION_2026, time(14, 0), _METALS),
    "fomc_minutes": (FOMC_MINUTES_2026, time(14, 0), _METALS),
}

ALL_KINDS = tuple(WEEKLY) + tuple(DATED)


def releases_for(series: str, start: datetime, end: datetime) -> list[tuple[datetime, str]]:
    """Every scheduled release instant in [start, end] (ET-aware bounds)
    that moves `series`, sorted. Pure: the schedule is known in advance,
    so calling this for a window's entry time is never look-ahead."""
    out: list[tuple[datetime, str]] = []
    day = start.astimezone(ET).date() - timedelta(days=1)
    last = end.astimezone(ET).date() + timedelta(days=1)
    while day <= last:
        for kind, (weekday, at, series_set) in WEEKLY.items():
            if series in series_set and day.weekday() == weekday:
                ts = datetime.combine(day, at, tzinfo=ET)
                if start <= ts <= end:
                    out.append((ts, kind))
        day += timedelta(days=1)
    for kind, (dates, at, series_set) in DATED.items():
        if series not in series_set:
            continue
        for d in dates:
            ts = datetime.combine(d, at, tzinfo=ET)
            if start <= ts <= end:
                out.append((ts, kind))
    return sorted(out)


def event_feature(series: str, entry: datetime, *, window_min: int = 15) -> dict:
    """The study's event feature for one entry instant: the nearest
    release kind within +/-window_min minutes, else 'none', plus the
    signed minutes to the nearest release of any relevant kind."""
    near = releases_for(series, entry - timedelta(days=2), entry + timedelta(days=2))
    if not near:
        return {"event_kind": "none", "event_within_15": False, "minutes_to_release": None}
    ts, kind = min(near, key=lambda p: abs((p[0] - entry).total_seconds()))
    delta_min = (ts - entry).total_seconds() / 60.0
    within = abs(delta_min) <= window_min
    return {"event_kind": kind if within else "none",
            "event_within_15": within,
            "minutes_to_release": round(delta_min, 1)}
