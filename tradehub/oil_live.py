"""The LIVE hourly WTI ladder for the Commodities tab hero (Kevin's
redesign, 2026-11-03). The journal's frozen ladder is the graded record;
this is the same v1 model recomputed against the market as it stands NOW
-- our probability is a pure function of the live price and the
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
from tradehub.data.hyperliquid import HyperliquidUnavailable, hyperliquid_oil_price
from tradehub.engines.oil_hourly import hourly_changes, hourly_prob, hourly_sigma, sigma_for
from tradehub.engines.fifteen_min import SERIES_COINS, WINDOW_MINUTES
from tradehub.journal.forecasters.fifteen_min import FifteenMinInputs, read_window
from tradehub.journal.forecasters.oil_hourly import (
    MIN_CHANGES,
    SERIES,
    HourlyInputs,
)
from tradehub.journal.kalshi_linked import quote_mid
from tradehub.oil_calibration import apply_map

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
# page can still title itself). The hero normally uses the live Hyperliquid perp; CL=F is only the fallback.
LIVE_MAX_PRICE_AGE = timedelta(minutes=25)

# The best strike (Kevin, 2026-11-03): where the model beats what the contract actually costs. A YES
# costs the ask and a NO costs one minus the bid, so a pick is always a price that could be paid, as
# Kalshi's own strike list shows it. Long shots and wide markets don't qualify. Picks get frozen and
# graded (tradehub/oil_itm.py), and the page shows that record next to the pick.
BEST_MIN_EDGE_PTS = 5.0
BEST_COST_BAND = (0.20, 0.80)
BEST_MAX_SPREAD = 0.08
TAKER_FEE_RATE = 0.07
_cache: dict[str, Any] = {"at": 0.0, "payload": None}
FIFTEEN_CACHE_SECONDS = 10.0
FIFTEEN_LABELS = {"KXWTI15M": "WTI", "KXBRENT15M": "Brent", "KXNATGAS15M": "Natural gas",
                  # The metals family (2026-11-09): the live read and the
                  # per-minute tick tape cover them from their first day, so
                  # their offsets grid accrues on live reads like oil's.
                  "KXGOLD15M": "Gold", "KXSILVER15M": "Silver", "KXCOPPER15M": "Copper"}
_fifteen_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def live_price(now: datetime, delayed_fn=None, free_fn=None) -> tuple[Any, str]:
    """(price, source): the free live perp, then the delayed print, named so the page can say which."""
    try:
        return (free_fn or hyperliquid_oil_price)(now), "hyperliquid"
    except HyperliquidUnavailable:
        return delayed_fn(), "cl=f"


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


# Picker v2 (spec 2026-11-09, options A + B): the same candidate shape and
# the same fee, but the probabilities are calibrated first (tradehub/
# oil_calibration.py) and the gross-edge bar is 15 points, not 5. The
# gated quantity is the same one v1 gated -- gross edge in points -- now
# computed on the calibrated probability; ranking stays by net edge with
# the taker fee inside it. Candidates also carry the raw probability and
# the row's quotes, so a freeze can store exactly what it saw.
PICKER_V2_MIN_EDGE_PTS = 15.0


def pick_best_strike_v2(rows: list[dict], calib) -> tuple[dict | None, dict | None]:
    """(the pick, the closest candidate) under the v2 rule. ``calib`` maps
    a raw YES probability to its calibrated value; a NO side's probability
    is 1 - calib(p_yes). Pure, like v1's picker."""
    candidates = []
    for row in rows:
        bid, ask, ours = row.get("yes_bid"), row.get("yes_ask"), row.get("ours")
        if bid is None or ask is None or ours is None or ask - bid > BEST_MAX_SPREAD:
            continue
        cal = calib(ours)
        for side, prob_raw, prob, cost in (("yes", ours, cal, ask),
                                           ("no", 1 - ours, 1 - cal, round(1 - bid, 4))):
            if BEST_COST_BAND[0] <= cost <= BEST_COST_BAND[1]:
                fee = TAKER_FEE_RATE * cost * (1 - cost)
                candidates.append({"strike": row["strike"], "side": side,
                                   "prob": round(prob, 4), "prob_raw": round(prob_raw, 4),
                                   "cost": cost, "yes_bid": bid, "yes_ask": ask,
                                   "edge_pts": round((prob - cost) * 100, 2),
                                   "net_pts": round((prob - cost - fee) * 100, 2)})
    if not candidates:
        return None, None
    closest = max(candidates, key=lambda c: c["net_pts"])
    return (closest if closest["edge_pts"] >= PICKER_V2_MIN_EDGE_PTS else None), closest


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
                geo: bool = True, event_ticker: str | None = None, calib_map=None) -> dict[str, Any]:
    """The live ladder payload. Degrades to {"state": "unavailable",
    "reason": ...} -- a named gap, never invented numbers.

    ``event_ticker`` targets one event directly, bypassing the roll rule
    (the T-10 freeze needs the imminent event the hero has already rolled
    past). ``calib_map`` switches the pick to the v2 rule (picker v2,
    spec 2026-11-09): rows gain ``ours_cal`` and the payload names the
    picker and map versions that produced its pick."""
    now = now or datetime.now(UTC)
    live = live or KalshiLive()
    inputs = inputs or HourlyInputs(live)
    events: dict[str, list] = {}
    for lm in live.open_markets(SERIES):
        events.setdefault(lm.market.event_ticker, []).append(lm)
    if event_ticker is not None:
        markets = events.get(event_ticker)
        if not markets:
            return {"state": "unavailable", "reason": f"{event_ticker} is not open"}
        picked = (event_ticker, markets)
    else:
        picked = pick_event(events, now)
    if picked is None:
        return {"state": "unavailable", "reason": "no open hourly event right now"}
    event, markets = picked
    minutes = (markets[0].market.close_time - now).total_seconds() / 60.0
    changes = hourly_changes(inputs.settled(now))
    if len(changes) < MIN_CHANGES:
        return {"state": "unavailable", "reason": "not enough settled hours yet"}
    price, price_source = live_price(now, delayed_fn=lambda: inputs.price(now))
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
        ours = round(hourly_prob(lm.market, price.value, sigma_h, minutes), 4)
        row = {"strike": lm.market.floor_strike,
               "ours": ours,
               "market": (round(m, 4) if (m := quote_mid(lm)) is not None else None),
               "yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask}
        if calib_map is not None:
            row["ours_cal"] = round(apply_map(calib_map, ours), 4)
        rows.append(row)
    if not rows:
        return {"state": "unavailable", "reason": "the event carries no strikes"}
    if calib_map is not None:
        best, closest = pick_best_strike_v2(rows, lambda p: apply_map(calib_map, p))
    else:
        best, closest = pick_best_strike(rows)
    return {
        "state": "live",
        "best": best,
        "closest": closest,
        "picker_version": "v2" if calib_map is not None else "v1",
        **({"calib_map_version": calib_map.version} if calib_map is not None else {}),
        "event": event,
        "close_time": markets[0].market.close_time.isoformat(),
        "minutes_to_close": round(minutes, 1),
        "as_of": now.isoformat(),
        "live_price": price.value,
        "price_source": price_source,
        "price_at": price.published_at.isoformat(),
        "price_age_minutes": round((now - price.published_at).total_seconds() / 60, 1),
        "sigma_h": round(sigma_h, 4),
        "sigma_eff": round(sigma_for(sigma_h, minutes), 4),
        "our_level": _crossing(rows, "ours"),
        "market_level": _crossing(rows, "market"),
        "geo": _geo_chip() if geo else None,
        "rows": rows,
    }


_hero_calib: dict[str, Any] = {"at": float("-inf"), "map": None}
HERO_CALIB_TTL_SECONDS = 1800.0


def _hero_calib_map():
    """The serving process's calibration map for the hero pick, refitted
    at most every 30 minutes on events already closed (so the walk-
    forward rule holds for any event it is applied to). Fail-soft like
    the geo chip: any failure leaves the ladder on the v1 pick and the
    payload's picker_version says so -- the page never breaks over a
    calibration read. Freezes never use this map; oil_itm fits its own
    per event with the exact cutoff."""
    now_s = time.monotonic()
    if now_s - _hero_calib["at"] < HERO_CALIB_TTL_SECONDS:
        return _hero_calib["map"]
    fitted = None
    try:
        from tradehub.core.supabase_client import get_client
        from tradehub.oil_calibration import fit_map, load_samples, pairs_before

        fitted = fit_map(pairs_before(load_samples(get_client()), datetime.now(UTC)))
    except Exception:  # noqa: BLE001 -- the v1 pick is the honest fallback
        fitted = None
    _hero_calib.update(at=now_s, map=fitted)
    return fitted


def live_ladder_cached() -> dict[str, Any]:
    """20-second server cache: the page polls every 30s and the Yahoo/
    Kalshi reads behind it should not scale with viewers."""
    now_s = time.monotonic()
    if _cache["payload"] is not None and now_s - _cache["at"] < CACHE_SECONDS:
        return _cache["payload"]
    payload = live_ladder(calib_map=_hero_calib_map())
    _cache.update(at=now_s, payload=payload)
    return payload


def _fifteen_market(series: str, live, inputs: FifteenMinInputs, now: datetime) -> dict[str, Any]:
    base = {"series": series, "label": FIFTEEN_LABELS[series]}
    window = timedelta(minutes=WINDOW_MINUTES)
    current = [lm for lm in live.open_markets(series) if lm.market.close_time - window <= now < lm.market.close_time]
    if not current:
        return {**base, "state": "unavailable", "reason": "no window open right now"}
    lm = current[0]
    read = read_window(lm.market.close_time, inputs.tape(SERIES_COINS[series], now), now)
    if read is None:
        return {**base, "state": "unavailable", "reason": "the live price tape can't support a read right now"}
    row = {"strike": 0.0, "ours": read["prob_up"], "yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask}
    best, closest = pick_best_strike([row])
    return {**base, "state": "live", "ticker": lm.market.ticker, "close_time": lm.market.close_time.isoformat(),
            "minutes_left": read["remaining_min"], "elapsed_min": read["elapsed_min"],
            "open_price": read["open_price"], "price": read["price"], "price_at": read["price_at"],
            "official_open": lm.market.floor_strike, "prob_up": round(read["prob_up"], 4),
            "market": (round(m, 4) if (m := quote_mid(lm)) is not None else None),
            "yes_bid": lm.quote.yes_bid, "yes_ask": lm.quote.yes_ask, "best": best, "closest": closest}


def fifteen_live(now: datetime | None = None, *, live=None, inputs: FifteenMinInputs | None = None) -> dict[str, Any]:
    """The live 15-minute read for the Oil page: the same math the journal freezes, on every open window, with
    Kalshi's current prices. Display only. One unreadable market says why and leaves the others up.
    Since 2026-11-09 the read covers the metals series too -- the per-minute tick tape
    (scripts/fifteen_min_tape.py) records through here, and the metals offsets grid
    accrues from the same live reads as the oil family's."""
    now = now or datetime.now(UTC)
    live = live or KalshiLive()
    inputs = inputs or FifteenMinInputs()
    markets = []
    for series in SERIES_COINS:
        try:
            markets.append(_fifteen_market(series, live, inputs, now))
        except Exception:  # noqa: BLE001 -- one bad market must not blank the panel
            markets.append({"series": series, "label": FIFTEEN_LABELS[series], "state": "unavailable",
                            "reason": "this market couldn't be read just now"})
    return {"state": "live", "as_of": now.isoformat(), "markets": markets}


def fifteen_live_cached() -> dict[str, Any]:
    """10-second server cache: the page polls every 15s."""
    now_s = time.monotonic()
    if _fifteen_cache["payload"] is not None and now_s - _fifteen_cache["at"] < FIFTEEN_CACHE_SECONDS:
        return _fifteen_cache["payload"]
    payload = fifteen_live()
    _fifteen_cache.update(at=now_s, payload=payload)
    return payload
