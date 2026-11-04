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
from datetime import UTC, datetime, timedelta
from typing import Any

from tradehub.data.kalshi_live import KalshiLive
from tradehub.data.pyth import HyperliquidUnavailable, PythUnavailable, hyperliquid_oil_price, pyth_oil_price
from tradehub.engines.oil_hourly import hourly_changes, hourly_prob, hourly_sigma, sigma_for
from tradehub.journal.forecasters.oil_hourly import (
    MIN_CHANGES,
    SERIES,
    HourlyInputs,
)
from tradehub.journal.kalshi_linked import quote_mid

MIN_MINUTES = 20.0
CACHE_SECONDS = 20.0

# The live hero's own price-age allowance (Kevin, 2026-11-03). Yahoo's CL=F
# tape runs ~10-15 minutes behind the exchange (CME redistribution delay),
# so the journal forecaster's 15-minute freshness gate -- right for a
# FROZEN, graded record -- made the live hero flicker to "unavailable" in
# ordinary trading and hide the ladder entirely. The hero is never scored:
# it stays live on a print up to 25 minutes old and stamps the print's age
# on the payload so the page can show it honestly. Older than that is a
# stuck feed, and the payload names it (with the event attached, so the
# page can still title itself). With a Pyth key the hero uses the feed Kalshi settles on instead.
LIVE_MAX_PRICE_AGE = timedelta(minutes=25)
PYTH_MAX_AGE_SECONDS = 120

# The best strike (Kevin, 2026-11-03): where the model beats what the contract actually costs. A YES
# costs the ask and a NO costs one minus the bid, so a pick is always a price that could be paid, as
# Kalshi's own strike list shows it. Long shots and wide markets don't qualify. Picks get frozen and
# graded (tradehub/oil_itm.py), and the page shows that record next to the pick.
BEST_MIN_EDGE_PTS = 5.0
BEST_COST_BAND = (0.20, 0.80)
BEST_MAX_SPREAD = 0.08
TAKER_FEE_RATE = 0.07
_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def live_price(now: datetime, pyth_fn=None, delayed_fn=None, free_fn=None) -> tuple[Any, str, str | None]:
    """(price, source, why Pyth wasn't used): the feed Kalshi settles on when it answers fresh, then the
    free perp, then the delayed print. `why` is public, so anyone can see whether the key is working
    without seeing the key."""
    try:
        price = (pyth_fn or pyth_oil_price)()
        age = (now - price.published_at).total_seconds()
        if age <= PYTH_MAX_AGE_SECONDS:
            if price.name == "PYTHOIL":
                return price, "pyth", None
            return price, "pyth-wti-future", "PYTHOIL isn't available; using the WTI future"
        why = f"Pyth's price was {round(age)} seconds old"
    except PythUnavailable as exc:
        why = str(exc)
    try:
        return (free_fn or hyperliquid_oil_price)(now), "hyperliquid", why
    except HyperliquidUnavailable:
        return delayed_fn(), "cl=f", why


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


def pick_best_strike(rows: list[dict]) -> tuple[dict | None, dict | None]:
    """(the pick, the closest candidate). The pick clears the edge bar; the closest may not, so the page
    can say how near it came. Pure, so the rule tests without a market."""
    candidates = []
    for row in rows:
        bid, ask, ours = row.get("yes_bid"), row.get("yes_ask"), row.get("ours")
        if bid is None or ask is None or ours is None or ask - bid > BEST_MAX_SPREAD:
            continue
        for side, prob, cost in (("yes", ours, ask), ("no", 1 - ours, round(1 - bid, 4))):
            if BEST_COST_BAND[0] <= cost <= BEST_COST_BAND[1]:
                fee = TAKER_FEE_RATE * cost * (1 - cost)
                candidates.append({"strike": row["strike"], "side": side, "prob": round(prob, 4), "cost": cost,
                                   "edge_pts": round((prob - cost) * 100, 2),
                                   "net_pts": round((prob - cost - fee) * 100, 2)})
    if not candidates:
        return None, None
    closest = max(candidates, key=lambda c: c["net_pts"])
    return (closest if closest["edge_pts"] >= BEST_MIN_EDGE_PTS else None), closest


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
    price, price_source, pyth_status = live_price(now, delayed_fn=lambda: inputs.price(now))
    if price is None or now - price.published_at > LIVE_MAX_PRICE_AGE:
        stale: dict[str, Any] = {"state": "unavailable",
                                 "reason": "the live WTI print is stale",
                                 "event": event,
                                 "close_time": markets[0].market.close_time.isoformat(),
                                 "minutes_to_close": round(minutes, 1)}
        if price is not None:
            stale["price_at"] = price.published_at.isoformat()
            stale["price_age_minutes"] = round((now - price.published_at).total_seconds() / 60, 1)
        return stale
    sigma_h = hourly_sigma(changes)
    rows = []
    for lm in sorted(markets, key=lambda m: m.market.floor_strike or 0.0):
        if lm.market.floor_strike is None:
            continue
        rows.append({"strike": lm.market.floor_strike,
                     "ours": round(hourly_prob(lm.market, price.value, sigma_h, minutes), 4),
                     "market": (round(m, 4) if (m := quote_mid(lm)) is not None else None),
                     "yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask})
    if not rows:
        return {"state": "unavailable", "reason": "the event carries no strikes"}
    best, closest = pick_best_strike(rows)
    return {
        "state": "live",
        "best": best,
        "closest": closest,
        "event": event,
        "close_time": markets[0].market.close_time.isoformat(),
        "minutes_to_close": round(minutes, 1),
        "as_of": now.isoformat(),
        "live_price": price.value,
        "price_source": price_source,
        "pyth_status": pyth_status,
        "price_at": price.published_at.isoformat(),
        "price_age_minutes": round((now - price.published_at).total_seconds() / 60, 1),
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
