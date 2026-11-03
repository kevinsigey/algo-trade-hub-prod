"""The geo shadow variant of the hourly WTI model -- `oil_wti_hourly` at
`wti-hourly-v2-geo-shadow`. Design + preregistration: goal files,
shadow-features-design-2026-11-02.md.

Sigma-widening ONLY; the mean never moves (geo signals carry risk, not a
defensible sign). The stress score reads the LATEST geo_snapshots batch
for Hormuz at freeze time, each signal against its own trailing median:

  gate entries (1h) at or below half their median -> +1
  intraday GPS-jamming share in its trailing top decile -> +1
  military aircraft at or above 3x their median (delta >= +200%) -> +1

Tiers: score 0 -> k = 1.0 (identical to v1; the row still freezes so the
log is complete), 1 -> 1.25, >= 2 -> 1.5. A feed whose health is not
"live" contributes 0 and marks the freeze geo_partial -- a silent feed
never widens sigma by absence (the plan's unknown-never-zero rule applied
to features). A provider failure also degrades to k = 1.0, stamped:
the shadow row must freeze or the paired record has gaps.

Grading gate (preregistered): after >= 200 settled contracts, paired
Brier vs v1 and vs Kalshi; promotion needs > 1 SE over v1 and is Kevin's
call. This row changes nothing about v1.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.journal.contract import CalendarEntry, Forecast
from tradehub.journal.forecasters.oil_hourly import OilWtiHourly

VERSION = "wti-hourly-v2-geo-shadow"
REGION = "hormuz"
K_BY_TIER = {0: 1.0, 1: 1.25}
K_TOP = 1.5

SIGNALS = (("ais", "tankers_gate_entries_1h"),
           ("adsb_jamming", "jamming_intraday"),
           ("adsb", "mil_total"))


def _median(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return statistics.median(clean) if clean else None


def stress_from_rows(current: list[dict], history: list[dict]) -> tuple[int, dict, bool]:
    """(score, contributions, partial). current: the latest snapshot batch;
    history: earlier rows (values only matter). Pure, so it tests without
    a database."""
    now_by_key = {(r["feed"], r["metric"]): r for r in current}
    past: dict[tuple[str, str], list[float]] = {}
    for r in history:
        if r.get("value") is not None:
            past.setdefault((r["feed"], r["metric"]), []).append(float(r["value"]))
    contributions: dict[str, Any] = {}
    partial = False
    score = 0

    def check(key: tuple[str, str], label: str, fires) -> None:
        nonlocal partial, score
        row = now_by_key.get(key)
        if row is None or row.get("health") != "live" or row.get("value") is None:
            partial = True
            contributions[label] = "unavailable"
            return
        median = _median(past.get(key, []))
        if median is None:
            partial = True
            contributions[label] = "no baseline yet"
            return
        value = float(row["value"])
        hit = bool(fires(value, median, past.get(key, [])))
        contributions[label] = {"value": value, "median": median, "fired": hit}
        score += 1 if hit else 0

    check(("ais", "tankers_gate_entries_1h"), "gate_entries_collapse",
          lambda v, m, _h: m > 0 and v <= 0.5 * m)
    check(("adsb_jamming", "jamming_intraday"), "jamming_top_decile",
          lambda v, _m, h: len(h) >= 10 and v >= sorted(h)[int(0.9 * (len(h) - 1))])
    check(("adsb", "mil_total"), "military_surge",
          lambda v, m, _h: m > 0 and v >= 3.0 * m)
    return score, contributions, partial


def k_for_score(score: int) -> float:
    return K_BY_TIER.get(score, K_TOP)


class GeoSnapshotProvider:
    """Reads geo_snapshots through the journal's supabase client factory.
    One latest-batch read plus the trailing values for the three signal
    metrics; raises on any failure and lets the forecaster degrade."""

    def __init__(self, get_client: Callable[[], Any]):
        self._get_client = get_client

    def __call__(self, now: datetime) -> tuple[list[dict], list[dict]]:
        supa = self._get_client()
        latest = (supa.table("geo_snapshots")
                  .select("feed,metric,value,health,taken_at")
                  .eq("region", REGION).order("taken_at", desc=True).limit(60)
                  .execute().data)
        if not latest:
            return [], []
        at = latest[0]["taken_at"]
        current = [r for r in latest if r["taken_at"] == at]
        since = (now - timedelta(days=30)).isoformat()
        keys = {f"{f}.{m}" for f, m in SIGNALS}
        history = (supa.table("geo_snapshots")
                   .select("feed,metric,value,taken_at")
                   .eq("region", REGION).gte("taken_at", since).lt("taken_at", at)
                   .order("taken_at", desc=True).limit(5000).execute().data)
        history = [r for r in history if f"{r['feed']}.{r['metric']}" in keys]
        return current, history


class OilWtiHourlyGeoShadow(OilWtiHourly):
    name, version = "oil_wti_hourly", VERSION

    def __init__(self, live, fetch, inputs, provider: Callable | None = None):
        super().__init__(live, fetch, inputs)
        self._provider = provider

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        score, contributions, partial, k = 0, {}, True, 1.0
        if self._provider is not None:
            try:
                current, history = self._provider(now)
                score, contributions, partial = stress_from_rows(current, history)
                k = k_for_score(score)
            except Exception:  # noqa: BLE001 -- degrade to v1, stamped; never skip the freeze
                contributions, partial = {"provider": "failed"}, True
        extra = {"geo_stress_score": score, "geo_k": k, "geo_partial": partial,
                 "geo_contributions": contributions,
                 "basis": "v1 with sigma widened by the Hormuz stress tier (shadow; preregistered)"}
        return self._forecast(entry, now, sigma_mult=k, extra=extra)


def build_oil_geo_shadow(live, fetch: Callable[[str], Any] | None = None,
                         inputs=None, provider: Callable | None = None) -> list:
    from tradehub.core.kalshi_feed import fetch_market
    from tradehub.core.supabase_client import get_client
    from tradehub.journal.forecasters.oil_hourly import HourlyInputs

    fetch = fetch or fetch_market
    inputs = inputs or HourlyInputs(live)
    provider = provider or GeoSnapshotProvider(get_client)
    return [OilWtiHourlyGeoShadow(live, fetch, inputs, provider)]
