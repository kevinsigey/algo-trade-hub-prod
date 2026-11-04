"""The geo2 shadow family: the sensitive Hormuz stress (`geo/stress.py`)
widening sigma on three existing models, each as its own shadow row.

  oil_wti_hourly @ wti-hourly-v5-geo2-shadow -- beside the v2 geo shadow,
  whose three binary thresholds and k in {1.0, 1.25, 1.5} it refines, not
  replaces (v2's record and gate are untouched).
  oil_wti @ wti-v2-geo2-shadow and natgas_daily @ natgas-v2-geo2-shadow --
  the daily grain, where a Hormuz event actually reprices: the same stress
  read widening the daily sigma. The daily adapters recompute the base
  model's probability from the inputs its own payload recorded (level,
  fitted model / sigma, horizon) with only sigma widened -- v1's code and
  record are untouched.

Sigma only, everywhere: the mean never moves (geo carries risk, not a
defensible sign). A provider failure degrades to k = 1.0, stamped, and
the row still freezes -- the paired record must not have gaps. Grading
gate (preregistered, mirroring v2): after >= 200 settled contracts,
paired Brier vs the base model and vs Kalshi; promotion needs > 1 SE
over the base and is Kevin's call.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.engines.oil import OilModel, oil_prob
from tradehub.geo.stress import SIGNALS, sensitive_stress
from tradehub.journal.contract import CalendarEntry, Forecast
from tradehub.journal.forecasters.natgas_daily import NatgasDaily, natgas_prob
from tradehub.journal.forecasters.oil import OilWti
from tradehub.journal.forecasters.oil_geo import REGION
from tradehub.journal.forecasters.oil_hourly import OilWtiHourly, sigma_for

HOURLY_VERSION = "wti-hourly-v5-geo2-shadow"
DAILY_VERSION = "wti-v2-geo2-shadow"
NATGAS_VERSION = "natgas-v2-geo2-shadow"
HISTORY_PER_METRIC = 700   # ~7 days of 15-minute batches


class Geo2SnapshotProvider:
    """Latest geo_snapshots batch plus per-metric trailing values (per-metric
    reads stay under the row cap a single wide read would hit). Raises on
    failure; the forecasters degrade to k = 1.0, stamped."""

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
        history: list[dict] = []
        keys = {(feed, metric) for _label, _w, legs, _kind in SIGNALS for feed, metric in legs}
        for feed, metric in sorted(keys):
            rows = (supa.table("geo_snapshots")
                    .select("feed,metric,value,taken_at")
                    .eq("region", REGION).eq("feed", feed).eq("metric", metric)
                    .lt("taken_at", at).order("taken_at", desc=True)
                    .limit(HISTORY_PER_METRIC).execute().data)
            history += rows
        return current, history


class _Geo2:
    """The shared stress read: (k, extra payload) for one freeze."""

    def __init__(self, provider: Callable | None):
        self._provider = provider

    def _widen(self, now: datetime) -> tuple[float, dict]:
        stress, k, contributions, partial = None, 1.0, {}, True
        if self._provider is not None:
            try:
                current, history = self._provider(now)
                stress, k, contributions, partial = sensitive_stress(current, history)
            except Exception:  # noqa: BLE001 -- degrade to the base model, stamped; never skip
                contributions, partial = {"provider": "failed"}, True
        extra = {"geo2_stress": stress, "geo2_k": k, "geo2_partial": partial,
                 "geo2_contributions": contributions,
                 "basis": "base model with sigma widened by the sensitive Hormuz "
                          "stress read (geo2 shadow; preregistered 2026-11-04)"}
        return k, extra


class OilWtiHourlyGeo2Shadow(_Geo2, OilWtiHourly):
    name, version = "oil_wti_hourly", HOURLY_VERSION

    def __init__(self, live, fetch, inputs, provider: Callable | None = None):
        OilWtiHourly.__init__(self, live, fetch, inputs)
        _Geo2.__init__(self, provider)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        k, extra = self._widen(now)
        return self._forecast(entry, now, sigma_mult=k, extra=extra)


class OilWtiDailyGeo2Shadow(_Geo2, OilWti):
    name, version = "oil_wti", DAILY_VERSION

    def __init__(self, live, fetch, inputs, provider: Callable | None = None):
        OilWti.__init__(self, live, fetch, inputs)
        _Geo2.__init__(self, provider)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        base = OilWti.forecast(self, entry, now)
        if base is None:
            return None
        k, extra = self._widen(now)
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        p = base.payload
        model = OilModel(alpha=p["alpha"], beta=p["beta"], sigma=p["sigma"] * k)
        prob = oil_prob(lm.market, p["last_settlement"], p["horizon_days"], p["cl_change_5"], model)
        return Forecast(self.name, self.version, entry.target, prob,
                        market_prob=base.market_prob,
                        payload={**p, "sigma": p["sigma"] * k, **extra})


class NatgasDailyGeo2Shadow(_Geo2, NatgasDaily):
    name, version = "natgas_daily", NATGAS_VERSION

    def __init__(self, live, fetch, inputs, provider: Callable | None = None):
        NatgasDaily.__init__(self, live, fetch, inputs)
        _Geo2.__init__(self, provider)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        base = NatgasDaily.forecast(self, entry, now)
        if base is None:
            return None
        k, extra = self._widen(now)
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        p = base.payload
        minutes = (lm.market.close_time - now).total_seconds() / 60.0
        sigma_d = p["sigma_d"] * k
        prob = natgas_prob(lm.market, p["live_price"], sigma_d, minutes)
        return Forecast(self.name, self.version, entry.target, prob,
                        market_prob=base.market_prob,
                        payload={**p, "sigma_d": sigma_d,
                                 "sigma_eff": sigma_for(sigma_d, minutes), **extra})


def build_oil_geo2(live, fetch: Callable[[str], Any] | None = None, provider=None) -> list:
    from tradehub.core.kalshi_feed import fetch_market
    from tradehub.core.supabase_client import get_client
    from tradehub.journal.forecasters.natgas_daily import DailyInputs
    from tradehub.journal.forecasters.oil import OilInputs
    from tradehub.journal.forecasters.oil_hourly import HourlyInputs

    fetch = fetch or fetch_market
    provider = provider or Geo2SnapshotProvider(get_client)
    return [OilWtiHourlyGeo2Shadow(live, fetch, HourlyInputs(live), provider),
            OilWtiDailyGeo2Shadow(live, fetch, OilInputs(live), provider),
            NatgasDailyGeo2Shadow(live, fetch, DailyInputs(live), provider)]
