"""The LIVE hourly WTI ladder for the Commodities tab hero (Kevin's
redesign, 2026-11-03). The journal's frozen ladder is the graded record;
this is the same v1 model recomputed against the market as it stands NOW
-- our probability is a pure function of the live CL=F price and the
minutes to close, so it tightens as the hour runs. Nothing here is
frozen or graded; the page labels it LIVE and keeps the frozen record
below it.

Target rule (Kevin's cadence): the hero always shows the next event,
and inside the last 20 minutes before a close it already shows the
FOLLOWING hour's event -- at :40 you are looking at the next hour, with
the prediction re-stamped every 20 minutes (:00/:20/:40) as the market
moves. Formally: the soonest event closing >= MIN_MINUTES out; if none
qualifies, the soonest event there is.

The Hormuz stress tier rides along as context (the geo shadow's current
score/k from the same pure scoring the journal variant uses) -- shown,
never folded into the headline probabilities: v1 stays v1.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from tradehub.data.kalshi_live import KalshiLive
from tradehub.engines.oil_hourly import hourly_changes, hourly_prob, hourly_sigma, sigma_for
from tradehub.journal.forecasters.oil_hourly import (
    MAX_PRICE_AGE,
    MIN_CHANGES,
    SERIES,
    HourlyInputs,
)
from tradehub.journal.kalshi_linked import quote_mid

MIN_MINUTES = 20.0
CACHE_SECONDS = 20.0
_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def pick_event(events: dict[str, list], now: datetime) -> tuple[str, list] | None:
    """events: event_ticker -> [LiveMarket]. The soonest event closing at
    least MIN_MINUTES out (Kevin's roll rule); else the soonest there is."""
    timed = []
    for event, markets in events.items():
        if not markets:
            continue
        minutes = (markets[0].market.close_time - now).total_seconds() / 60.0
        timed.append((minutes, event, markets))
    if not timed:
        return None
    timed.sort(key=lambda t: t[0])
    for minutes, event, markets in timed:
        if minutes >= MIN_MINUTES:
            return event, markets
    return timed[0][1], timed[0][2]


def _crossing(rows: list[dict], key: str) -> float | None:
    """Interpolated strike where P(above) crosses 50% (the frontend hero's
    rule, server-side so every client reads the same levels)."""
    for a, b in zip(rows, rows[1:], strict=False):
        pa, pb = a.get(key), b.get(key)
        if pa is None or pb is None:
            continue
        if pa >= 0.5 >= pb and pa != pb:
            return a["strike"] + ((pa - 0.5) / (pa - pb)) * (b["strike"] - a["strike"])
    return None


def _geo_chip() -> dict | None:
    try:
        from tradehub.core.supabase_client import get_client
        from tradehub.journal.forecasters.oil_geo import (
            GeoSnapshotProvider,
            k_for_score,
            stress_from_rows,
        )

        current, history = GeoSnapshotProvider(get_client)(datetime.now(UTC))
        score, _contrib, partial = stress_from_rows(current, history)
        return {"stress_score": score, "k": k_for_score(score), "partial": partial}
    except Exception:  # noqa: BLE001 -- context only; its absence never blocks the ladder
        return None


def live_ladder(now: datetime | None = None, *, live=None, inputs: HourlyInputs | None = None,
                geo: bool = True) -> dict[str, Any]:
    """The live ladder payload. Degrades to {"state": "unavailable",
    "reason": ...} -- a named gap, never invented numbers."""
    now = now or datetime.now(UTC)
    live = live or KalshiLive()
    inputs = inputs or HourlyInputs(live)
    events: dict[str, list] = {}
    for lm in live.open_markets(SERIES):
        events.setdefault(lm.market.event_ticker, []).append(lm)
    picked = pick_event(events, now)
    if picked is None:
        return {"state": "unavailable", "reason": "no open hourly event right now"}
    event, markets = picked
    minutes = (markets[0].market.close_time - now).total_seconds() / 60.0
    changes = hourly_changes(inputs.settled(now))
    if len(changes) < MIN_CHANGES:
        return {"state": "unavailable", "reason": "not enough settled hours yet"}
    price = inputs.price(now)
    if price is None or now - price.published_at > MAX_PRICE_AGE:
        return {"state": "unavailable", "reason": "the live WTI print is stale"}
    sigma_h = hourly_sigma(changes)
    rows = []
    for lm in sorted(markets, key=lambda m: m.market.floor_strike or 0.0):
        if lm.market.floor_strike is None:
            continue
        rows.append({"strike": lm.market.floor_strike,
                     "ours": round(hourly_prob(lm.market, price.value, sigma_h, minutes), 4),
                     "market": (round(m, 4) if (m := quote_mid(lm)) is not None else None)})
    if not rows:
        return {"state": "unavailable", "reason": "the event carries no strikes"}
    return {
        "state": "live",
        "event": event,
        "close_time": markets[0].market.close_time.isoformat(),
        "minutes_to_close": round(minutes, 1),
        "as_of": now.isoformat(),
        "live_price": price.value,
        "price_at": price.published_at.isoformat(),
        "sigma_h": round(sigma_h, 4),
        "sigma_eff": round(sigma_for(sigma_h, minutes), 4),
        "our_level": _crossing(rows, "ours"),
        "market_level": _crossing(rows, "market"),
        "geo": _geo_chip() if geo else None,
        "rows": rows,
    }


def live_ladder_cached() -> dict[str, Any]:
    """20-second server cache: the page polls every 30s and the Yahoo/
    Kalshi reads behind it should not scale with viewers."""
    now_s = time.monotonic()
    if _cache["payload"] is not None and now_s - _cache["at"] < CACHE_SECONDS:
        return _cache["payload"]
    payload = live_ladder()
    _cache.update(at=now_s, payload=payload)
    return payload
