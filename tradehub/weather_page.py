"""The /api/weather composition (phase-3): today's weather forecast vs
Kalshi vs climatology, plus settled history.

Moved out of the API module (Nov 12, step 5) so the hourly precompute
builds the identical payload the endpoint serves. Read failures raise
WeatherReadError naming the table; the endpoint maps it to the same
fault response it has always returned.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tradehub.journal import store


class WeatherReadError(Exception):
    """A journal read failed; `table` names the source for the fault mapping."""

    def __init__(self, table: str):
        super().__init__(table)
        self.table = table


def target_day(target: str):
    """The operating day of a Kalshi journal target: 'kalshi:KXHIGHNY-26OCT16-T75' -> 2026-10-16.

    The date is the SECOND dash-separated part of the ticker (`%y%b%d`); the last part is the strike or
    city. Parsed to a real date so days compare chronologically across months (as text, '26OCT' sorts
    after '26NOV').
    """
    parts = target.removeprefix("kalshi:").split("-")
    if len(parts) < 2:
        return None
    try:
        return datetime.strptime(parts[1], "%y%b%d").date()
    except ValueError:
        return None


def build_weather(supabase) -> dict[str, Any]:
    """Today's weather forecast vs Kalshi vs climatology, plus settled history.

    Read from journal tables. No new forecasting. The forecaster names are:
    - weather_high/low/rain: the ensemble model
    - baseline_climatology_weather_*: the climatology baseline
    - kalshi_implied_weather_*: the Kalshi market probability
    """
    # Weather forecaster patterns
    weather_forecasters = {
        "ensemble": ("weather_high", "weather_low", "weather_rain"),
        "climatology": ("baseline_climatology_weather_high", "baseline_climatology_weather_low",
                        "baseline_climatology_weather_rain"),
        "kalshi": ("kalshi_implied_weather_high", "kalshi_implied_weather_low",
                   "kalshi_implied_weather_rain"),
    }

    names = [n for group in weather_forecasters.values() for n in group]
    try:
        forecasts = store.select_all(supabase, "journal_forecasts",
                                     lambda q: q.in_("forecaster", names), ("frozen_at",))
    except Exception as exc:  # noqa: BLE001 - the endpoint maps this to its fault response
        raise WeatherReadError("journal_forecasts") from exc
    try:
        settlements = store.select_all(supabase, "journal_settlements",
                                       lambda q: q, ("settled_at",))
    except Exception as exc:  # noqa: BLE001 - the endpoint maps this to its fault response
        raise WeatherReadError("journal_settlements") from exc

    # Group by target, keep only weather forecasters
    # Also track the payload from kalshi_implied for market metadata (fallback to ensemble if needed)
    by_target: dict[str, dict[str, float]] = {}
    target_metadata: dict[str, dict[str, Any]] = {}
    # First pass: collect all forecasts and capture metadata from kalshi_implied
    for row in forecasts:
        target = row.get("target", "")
        forecaster = row.get("forecaster", "")
        prob = row.get("probability")
        if prob is None:
            continue
        # Check if this is a weather forecaster
        is_weather = False
        for kind, names in weather_forecasters.items():
            if forecaster in names:
                is_weather = True
                break
        if not is_weather:
            continue
        if target not in by_target:
            by_target[target] = {}
        # Map forecaster to kind
        for kind, names in weather_forecasters.items():
            if forecaster in names:
                by_target[target][kind] = float(prob)
                break
        # Capture market metadata from kalshi_implied payload (primary source)
        if forecaster.startswith("kalshi_implied_") and row.get("payload"):
            payload = row["payload"]
            target_metadata[target] = {
                "strike_type": payload.get("strike_type"),
                "floor_strike": payload.get("floor_strike"),
                "cap_strike": payload.get("cap_strike"),
                "yes_sub_title": payload.get("yes_sub_title"),
                "no_sub_title": payload.get("no_sub_title"),
            }
    # Second pass: for targets without metadata, try to get from ensemble forecaster payload
    for row in forecasts:
        target = row.get("target", "")
        forecaster = row.get("forecaster", "")
        if target in target_metadata:
            continue  # already have metadata
        if not forecaster.startswith("weather_") or forecaster.startswith("baseline_") or forecaster.startswith("kalshi_"):
            continue
        if not row.get("payload"):
            continue
        payload = row["payload"]
        # Only set if we actually have the fields
        if any(k in payload for k in ("strike_type", "floor_strike", "cap_strike", "yes_sub_title", "no_sub_title")):
            target_metadata[target] = {
                "strike_type": payload.get("strike_type"),
                "floor_strike": payload.get("floor_strike"),
                "cap_strike": payload.get("cap_strike"),
                "yes_sub_title": payload.get("yes_sub_title"),
                "no_sub_title": payload.get("no_sub_title"),
            }

    # Split into today (the operating day is today or later in Eastern time) and settled history
    from zoneinfo import ZoneInfo
    today_day = datetime.now(ZoneInfo("America/New_York")).date()
    outcome_by_target = {st.get("target"): st for st in settlements}
    today = []
    settled = []
    for target, probs in by_target.items():
        day = target_day(target)
        if day is None:
            continue
        meta = target_metadata.get(target, {})
        row = {
            "target": target,
            "date": day.isoformat(),
            "ensemble": probs.get("ensemble"),
            "kalshi": probs.get("kalshi"),
            "climatology": probs.get("climatology"),
            "strike_type": meta.get("strike_type"),
            "floor_strike": meta.get("floor_strike"),
            "cap_strike": meta.get("cap_strike"),
            "yes_sub_title": meta.get("yes_sub_title"),
            "no_sub_title": meta.get("no_sub_title"),
        }
        if day >= today_day:
            today.append(row)
            continue
        st = outcome_by_target.get(target)
        if st is None:
            continue                       # a past day not settled yet is not history
        row["outcome"] = st.get("outcome")
        row["realized_value"] = st.get("realized_value")
        row["settled_at"] = st.get("settled_at")
        settled.append(row)
    settled.sort(key=lambda r: (r["date"], r["target"]), reverse=True)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "today": today,
        "settled": settled,
    }


# ════════════════════════════════════════════════════════════════════════════

