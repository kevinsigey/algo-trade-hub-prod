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
from tradehub.engines.oil_hourly import hourly_changes, hourly_prob, hourly_sigma, sigma_for
from tradehub.journal.forecasters.oil_hourly import (
    MIN_CHANGES,
    SERIES,
    HourlyInputs,
)
from tradehub.data.wti import wti_minute_tape
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
# page can still title itself). The real fix is a real-time source --
# Kalshi settles these markets on Pyth, but Pyth's Hermes price updates
# now sit behind an API key (401 without one, verified 2026-11-03); that
# key is Kevin's call.
LIVE_MAX_PRICE_AGE = timedelta(minutes=25)
TAPE_MAX_AGE = timedelta(minutes=60)

# The ITM line (Kevin, 2026-11-03): on the live ladder, the strike where
# the bet is a bit more likely than a coin flip AND we like it more than
# Kalshi does AND the tape has kept clear of it -- the strike was never
# the 50% level over the last stretch. A selection rule on the v1 Normal
# model, nothing more; picks get frozen and graded (tradehub/oil_itm.py).
ITM_BAND = (0.55, 0.75)
ITM_MIN_GAP = 0.03
ITM_LOOKBACK_MIN = 10
ITM_MIN_BARS = 6
ITM_MIN_CLEARANCE = 0.05
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


def pick_itm_line(rows: list[dict], tape: list, now: datetime,
                  live_price: float) -> dict | None:
    """The ITM pick from a live ladder, or None. Pure, so the rule tests
    without a market. `tape` is [(bar time, close)] oldest first."""
    if not tape:
        return None
    # The window is the tape's OWN trailing minutes, not the wall clock's:
    # the CL=F tape runs ~10-15 minutes behind the exchange, so a window
    # keyed to `now` was always empty and the pick could never fire. A tape
    # whose last bar is older than TAPE_MAX_AGE is a dead feed, not a
    # stable one -- no pick.
    end = max(ts for ts, _c in tape)
    if now - end > TAPE_MAX_AGE:
        return None
    window = [(ts, c) for ts, c in tape
              if 0 <= (end - ts).total_seconds() <= ITM_LOOKBACK_MIN * 60]
    if len(window) < ITM_MIN_BARS:
        return None
    candidates = []
    for row in rows:
        ours, market = row.get("ours"), row.get("market")
        if ours is None or market is None:
            continue
        if not ITM_BAND[0] <= ours <= ITM_BAND[1] or ours - market < ITM_MIN_GAP:
            continue
        strike = row["strike"]
        sides = {(c > strike) - (c < strike) for _ts, c in window}
        if len(sides) != 1 or 0 in sides:
            continue  # the tape crossed (or touched) the strike: it WAS the level
        if min(abs(c - strike) for _ts, c in window) < ITM_MIN_CLEARANCE:
            continue  # too close to call clear
        candidates.append(row)
    if not candidates:
        return None
    best = min(candidates, key=lambda r: abs(r["strike"] - live_price))
    return {"strike": best["strike"], "ours": best["ours"], "market": best["market"],
            "gap_pts": round((best["ours"] - best["market"]) * 100, 1),
            "clear_bars": len(window)}


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
                geo: bool = True, tape_fn=wti_minute_tape) -> dict[str, Any]:
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
                     "market": (round(m, 4) if (m := quote_mid(lm)) is not None else None)})
    if not rows:
        return {"state": "unavailable", "reason": "the event carries no strikes"}
    itm = None
    try:
        itm = pick_itm_line(rows, tape_fn(), now, price.value)
    except Exception:  # noqa: BLE001 -- the pick is additive; its absence never sinks the ladder
        itm = None
    return {
        "state": "live",
        "itm": itm,
        "event": event,
        "close_time": markets[0].market.close_time.isoformat(),
        "minutes_to_close": round(minutes, 1),
        "as_of": now.isoformat(),
        "live_price": price.value,
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
