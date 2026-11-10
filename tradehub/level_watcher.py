"""Spec D — the Level Watcher / Trigger Service, Stage 1 (Rung 1).

Frozen in docs/superpowers/specs/2026-11-09-level-watcher-freeze.md,
which governs this module: a deterministic, rules-only service that
watches price levels with conditions (cross, touch-and-hold, zone
entry, VWAP side, volume multiple, time window, file state, FOMC
blackout) and acts on the bottom rung of the authority ladder — ALERT.
Stage 1 contains no order-placement and no staged-ticket code: a watch
carries its requested rung, but every fire is stamped
rung_effective = 1 and lands in the trigger log (watcher_fires) plus
the alert outbox (watcher_alerts). Rungs 2–3 are later stages.

The Spec C amendment is structural here: band-crossing watches do not
detect anything themselves. The tick observes intraday zones against
Spec C's stored bands, and when a zone moved it drives
band_crossing.run_watcher_evaluation — Spec C's own state machine
writes the crossing rows (scan_kind='watcher') and the alert fires
from that logged crossing. One detector, ever.

Data is Alpaca only (1-min bars + latest trade, the auto-trader's
read path through alpaca_paper's host and headers). No yfinance
anywhere in the firing path. All state lives in the store — the tick
is stateless, so a restart re-derives everything from bars + rows and
the day's fire (plus the unique idempotency key) prevents any
double-fire on a re-touch.
"""
from __future__ import annotations

import statistics
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from tradehub.portfolio import alpaca_paper
from tradehub.valuation import band_crossing as bc

ET = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)

WATCHES = "level_watches"
FIRES = "watcher_fires"
ALERTS = "watcher_alerts"
HEARTBEATS = "watcher_heartbeats"
GOV_GROUPS = "watcher_governor_groups"
GOV_STATE = "watcher_governor_state"
FAMILY_STATE = "watcher_family_state"
DAY_CACHE = "watcher_day_cache"

STAGE = 1
RUNG_CAP = 1
DEMOTION_GATE = 20          # graded triggers before a family can demote
HEARTBEAT_EVERY = timedelta(minutes=15)
DOWN_AFTER = timedelta(minutes=30)   # two missed heartbeats
BLACKOUT_MINUTES = 30
BASELINE_SESSIONS = 10


# ── session helpers ──────────────────────────────────────────────────────────

def is_market_hours(now: datetime) -> bool:
    et = now.astimezone(ET)
    return et.weekday() < 5 and SESSION_OPEN <= et.time() < SESSION_CLOSE


def session_date_of(now: datetime) -> str:
    return now.astimezone(ET).date().isoformat()


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


# ── blackout (FOMC frozen calendar; CPI is a named gap) ─────────────────────

_FOMC_TIMES: tuple[datetime, ...] | None = None


def _fomc_times() -> tuple[datetime, ...]:
    """FOMC statement datetimes (ET, tz-naive wall times) from the hub's
    frozen statement calendar — the authoritative source, never a
    scraped or inferred list."""
    global _FOMC_TIMES
    if _FOMC_TIMES is None:
        from tradehub.workshop.fomc_calendar import statement_times

        frame = statement_times()
        _FOMC_TIMES = tuple(
            ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            for ts in frame["time"])
    return _FOMC_TIMES


def fomc_blackout(now: datetime) -> bool:
    """True inside ±30 minutes of an FOMC statement time. CPI releases
    are NOT covered: the hub has no stored BLS release calendar (the
    freeze doc names the gap; read_surface carries cpi_blackout_gap)."""
    et_naive = now.astimezone(ET).replace(tzinfo=None)
    window = timedelta(minutes=BLACKOUT_MINUTES)
    return any(abs(et_naive - ts) <= window for ts in _fomc_times())


# ── bar math (pure; bars are dicts {t, o, h, l, c, v}, ET-aware) ────────────

def completed_bars(bars: list[dict], now: datetime) -> list[dict]:
    """Bars whose minute has fully elapsed by `now`."""
    return [b for b in bars if b["t"] + timedelta(minutes=1) <= now]


def session_vwap(bars: list[dict]) -> float | None:
    num = den = 0.0
    for b in bars:
        v = float(b.get("v") or 0.0)
        if v <= 0:
            continue
        typical = (float(b["h"]) + float(b["l"]) + float(b["c"])) / 3.0
        num += typical * v
        den += v
    return num / den if den > 0 else None


def _trailing_run(bars: list[dict], pred) -> int:
    run = 0
    for b in reversed(bars):
        if pred(b):
            run += 1
        else:
            break
    return run


def check_conditions(watch: dict, *, bars: list[dict], price: float,
                     now: datetime, baseline_volume: float | None = None,
                     t1: str | None = None) -> tuple[bool, dict]:
    """Evaluate a level watch's trigger + conditions against completed
    bars and the latest trade. Pure and deterministic: the same bars
    always give the same answer, which is what makes a restart
    re-touch safe. A condition that cannot be evaluated from data
    FAILS — the watcher never fires on missing data."""
    conds = watch.get("conditions") or {}
    level = watch.get("level")
    detail: dict = {"trigger": {}, "conditions": {}}
    trig: dict = {"type": watch.get("trigger_type"), "pass": False}
    detail["trigger"] = trig

    ttype = watch.get("trigger_type")
    if ttype in ("cross_up", "cross_down"):
        if level is None or not bars:
            trig["reason"] = "no_completed_bars" if level is not None \
                else "no_level"
        else:
            prev_close = float(bars[-1]["c"])
            trig["prev_close"] = prev_close
            if ttype == "cross_up":
                trig["pass"] = prev_close <= float(level) \
                    and price > float(level)
            else:
                trig["pass"] = prev_close >= float(level) \
                    and price < float(level)
    elif ttype == "touch_and_hold":
        hold = int(watch.get("hold_minutes") or 1)
        trig["hold_minutes"] = hold
        if level is None or not bars:
            trig["reason"] = "no_completed_bars" if level is not None \
                else "no_level"
        else:
            if price >= float(level):
                run = _trailing_run(bars, lambda b: float(b["l"]) >= float(level))
                trig["side"] = "up"
            else:
                run = _trailing_run(bars, lambda b: float(b["h"]) <= float(level))
                trig["side"] = "down"
            trig["run"] = run
            trig["pass"] = run >= hold
    elif ttype == "zone_entry":
        lo = float(level) if level is not None else None
        hi = watch.get("level_hi")
        hi = float(hi) if hi is not None else lo
        hold = int(watch.get("hold_minutes") or 0)
        trig["hold_minutes"] = hold
        if lo is None or not bars:
            trig["reason"] = "no_completed_bars" if lo is not None \
                else "no_level"
        else:
            inside = lo <= price <= hi
            run = _trailing_run(
                bars, lambda b: lo <= float(b["c"]) <= hi)
            # An entry needs an outside close before the in-zone run —
            # a name that opened inside the zone never entered it.
            preceded = run < len(bars)
            trig.update({"inside": inside, "run": run,
                         "preceded_by_outside": preceded})
            trig["pass"] = bool(inside and preceded and run >= max(hold, 1))
    else:
        trig["reason"] = f"unknown_trigger_type:{ttype}"

    checks = detail["conditions"]

    # Blackout is evaluated for every watch (default on; event watches
    # are exempt by design).
    if conds.get("event_watch"):
        checks["blackout"] = {"pass": True, "reason": "event_watch_exempt"}
    elif conds.get("blackout", True) and fomc_blackout(now):
        checks["blackout"] = {"pass": False, "reason": "fomc_blackout"}
    else:
        checks["blackout"] = {"pass": True}

    if conds.get("vwap_side"):
        vwap = session_vwap(bars)
        if vwap is None:
            checks["vwap_side"] = {"pass": False, "reason": "no_vwap"}
        else:
            want = conds["vwap_side"]
            ok = price > vwap if want == "above" else price < vwap
            checks["vwap_side"] = {"pass": bool(ok), "vwap": round(vwap, 4),
                                   "want": want}
    if conds.get("volume_multiple") is not None:
        mult = float(conds["volume_multiple"])
        if baseline_volume is None:
            checks["volume_multiple"] = {
                "pass": False, "reason": "baseline_unavailable"}
        elif not bars:
            checks["volume_multiple"] = {
                "pass": False, "reason": "no_completed_bars"}
        else:
            vol = float(bars[-1].get("v") or 0.0)
            checks["volume_multiple"] = {
                "pass": vol >= mult * baseline_volume, "volume": vol,
                "baseline_median": baseline_volume, "multiple": mult}
    if conds.get("time_window"):
        win = conds["time_window"] or {}
        start = _hhmm(win.get("start_et"))
        end = _hhmm(win.get("end_et"))
        t = now.astimezone(ET).time()
        ok = start is not None and end is not None and start <= t < end
        checks["time_window"] = {"pass": bool(ok), "window": win}
    if conds.get("file_state"):
        want = conds["file_state"]
        if t1 is None:
            checks["file_state"] = {"pass": False,
                                    "reason": "no_t1_classification",
                                    "want": want}
        else:
            ok = t1 in ("improved", "intact") if want == "intact_or_better" \
                else t1 == "deteriorated"
            checks["file_state"] = {"pass": bool(ok), "t1": t1, "want": want}

    fired = bool(trig["pass"]) and all(
        c["pass"] for c in checks.values())
    return fired, detail


def _hhmm(value) -> time | None:
    if not value:
        return None
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except (ValueError, TypeError):
        return None


# ── the Alpaca feed (firing path; the auto-trader's read pattern) ───────────

class AlpacaFeed:
    """1-min bars + latest trade from data.alpaca.markets, read with
    the main book's paper keys via alpaca_paper's headers — the same
    host the auto-trader's latest-price reads use. Bars carry
    feed=iex (the feed the paper keys hold). No yfinance."""

    def __init__(self, *, session=requests, book: str | None = "main"):
        self._session = session
        self._book = book

    def _bars(self, symbol: str, start: datetime, end: datetime) -> list[dict]:
        params = {"timeframe": "1Min",
                  "start": start.astimezone(timezone.utc).isoformat(),
                  "end": end.astimezone(timezone.utc).isoformat(),
                  "feed": "iex", "limit": 10000, "sort": "asc"}
        out: list[dict] = []
        while True:
            resp = self._session.get(
                alpaca_paper.DATA_BASE + f"/v2/stocks/{symbol}/bars",
                params=params, headers=alpaca_paper._headers(self._book),
                timeout=15)
            resp.raise_for_status()
            body = resp.json() or {}
            for b in body.get("bars") or []:
                out.append({
                    "t": datetime.fromisoformat(
                        str(b["t"]).replace("Z", "+00:00")).astimezone(ET),
                    "o": float(b["o"]), "h": float(b["h"]),
                    "l": float(b["l"]), "c": float(b["c"]),
                    "v": float(b.get("v") or 0.0)})
            token = body.get("next_page_token")
            if not token:
                return out
            params["page_token"] = token

    def bars_today(self, symbol: str, now: datetime) -> list[dict]:
        day = now.astimezone(ET).date()
        start = datetime.combine(day, SESSION_OPEN, tzinfo=ET)
        return self._bars(symbol, start, now)

    def bars_between(self, symbol: str, start: datetime,
                     end: datetime) -> list[dict]:
        return self._bars(symbol, start, end)

    def latest_trade(self, symbol: str) -> float:
        return alpaca_paper.latest_price(symbol, session=self._session,
                                         book=self._book)


# ── volume baselines (per symbol + session, cached in the store) ────────────

def baseline_median_volume(client, feed, symbol: str, minute_hhmm: str,
                           session_date: str, now: datetime) -> float | None:
    """Median volume of the same clock minute over the prior
    BASELINE_SESSIONS trading sessions (same feed). Computed once per
    (symbol, session date) and cached in watcher_day_cache; the
    baseline is a property of the day, not of the tick."""
    cached = _day_cache(client, symbol, session_date)
    if cached is None:
        cached = _compute_day_baseline(feed, symbol, session_date, now)
        if cached is not None:
            try:
                client.table(DAY_CACHE).insert({
                    "symbol": symbol, "session_date": session_date,
                    "payload": cached,
                    "created_at": now.isoformat()}).execute()
            except Exception:  # noqa: BLE001 -- a cache write never blocks
                pass
    if not cached:
        return None
    value = (cached.get("medians") or {}).get(minute_hhmm)
    return float(value) if value is not None else None


def _day_cache(client, symbol: str, session_date: str) -> dict | None:
    try:
        rows = (client.table(DAY_CACHE).select("payload")
                .eq("symbol", symbol).eq("session_date", session_date)
                .execute().data) or []
    except Exception:  # noqa: BLE001 -- no cache yet is a compute case
        return None
    return rows[0].get("payload") if rows else None


def _compute_day_baseline(feed, symbol: str, session_date: str,
                          now: datetime) -> dict | None:
    from datetime import date as _date

    day = _date.fromisoformat(session_date)
    volumes: dict[str, list[float]] = {}
    sessions = 0
    cursor = day - timedelta(days=1)
    for _ in range(25):  # walk back over weekends/holidays to 10 sessions
        if sessions >= BASELINE_SESSIONS:
            break
        if cursor.weekday() < 5:
            start = datetime.combine(cursor, SESSION_OPEN, tzinfo=ET)
            end = datetime.combine(cursor, SESSION_CLOSE, tzinfo=ET)
            try:
                bars = feed.bars_between(symbol, start, end)
            except Exception:  # noqa: BLE001 -- a gap day is skipped
                bars = []
            if bars:
                sessions += 1
                for b in bars:
                    key = b["t"].strftime("%H:%M")
                    volumes.setdefault(key, []).append(float(b.get("v") or 0.0))
        cursor -= timedelta(days=1)
    if sessions == 0:
        return None
    medians = {k: statistics.median(v) for k, v in volumes.items()
              if len(v) >= 5}
    return {"medians": medians, "sessions": sessions}


# ── store helpers ────────────────────────────────────────────────────────────

def _rows(client, table: str, *, filters: dict | None = None,
          order: str | None = None, desc: bool = False,
          limit: int | None = None) -> list[dict]:
    try:
        q = client.table(table).select("*")
        for col, val in (filters or {}).items():
            q = q.eq(col, val)
        if order:
            q = q.order(order, desc=desc)
        if limit:
            q = q.limit(limit)
        return q.execute().data or []
    except Exception:  # noqa: BLE001 -- pre-migration reads as empty
        return []


def _last_heartbeat(client) -> datetime | None:
    rows = _rows(client, HEARTBEATS, order="at", desc=True, limit=1)
    return _parse_ts(rows[0].get("at")) if rows else None


def watcher_status(client, *, now: datetime | None = None) -> dict:
    """Live health from the heartbeat record: in market hours a
    heartbeat older than two missed beats reads DOWN on the surface
    even if nothing else is running to say so."""
    now = now or datetime.now(timezone.utc)
    last = _last_heartbeat(client)
    if not is_market_hours(now):
        state = "idle"
    elif last is None:
        state = "down"
    else:
        state = "up" if now - last <= DOWN_AFTER else "down"
    return {"state": state,
            "last_heartbeat": last.isoformat() if last else None,
            "age_seconds": (round((now - last).total_seconds())
                            if last else None)}


def _down_alert_once(client, *, last_hb: datetime, now: datetime) -> bool:
    """One watcher_down alert per outage, keyed on the last heartbeat
    the outage started from."""
    for row in _rows(client, ALERTS, filters={"kind": "watcher_down"},
                     order="id", desc=True, limit=5):
        evidence = row.get("evidence") or {}
        if evidence.get("last_heartbeat") == last_hb.isoformat():
            return False
    _write_alert(
        client, kind="watcher_down",
        title="Level watcher DOWN — missed heartbeats",
        body=(f"The level watcher's last heartbeat was "
              f"{last_hb.astimezone(ET).strftime('%H:%M ET')} and two "
              f"beats have been missed; the watcher is treated as DOWN "
              f"until a heartbeat lands. A dead watcher is not a quiet "
              f"market — no watch fired or could fire in the gap."),
        evidence={"last_heartbeat": last_hb.isoformat(),
                  "observed_at": now.isoformat()}, now=now)
    return True


def check_down_alert(client, *, now: datetime) -> bool:
    """Shared by the tick and the grading run: if the heartbeat record
    shows a >30-minute gap in market hours, record the outage once."""
    if not is_market_hours(now):
        return False
    last = _last_heartbeat(client)
    if last is None or now - last <= DOWN_AFTER:
        return False
    return _down_alert_once(client, last_hb=last, now=now)


def _write_alert(client, *, kind: str, title: str, body: str,
                 watch_id=None, family: str | None = None,
                 evidence: dict | None = None, now: datetime) -> dict:
    rows = client.table(ALERTS).insert({
        "kind": kind, "watch_id": watch_id, "family": family,
        "title": title, "body": body, "evidence": evidence or {},
        "status": "pending", "created_at": now.isoformat(),
    }).execute().data or []
    return rows[0] if rows else {}


def _fired_today(client, watch_id: int, session_date: str) -> bool:
    rows = _rows(client, FIRES, filters={"watch_id": watch_id,
                                         "session_date": session_date},
                 limit=1)
    return bool(rows)


def _path_window(bars: list[dict], center: datetime,
                 minutes: int) -> list[dict]:
    lo = center - timedelta(minutes=minutes)
    return [{"t": b["t"].isoformat(), "o": b["o"], "h": b["h"],
             "l": b["l"], "c": b["c"], "v": b["v"]}
            for b in bars if lo <= b["t"] <= center]


def _fire(client, watch: dict, *, now: datetime, instrument: str,
          price: float, detail: dict, path_past: list[dict] | None,
          crossing_ids: list | None, idempotency_key: str) -> dict:
    session = session_date_of(now)
    inserted = client.table(FIRES).insert({
        "watch_id": watch.get("id"), "family": watch.get("family"),
        "instrument": instrument, "session_date": session,
        "fired_at": now.isoformat(), "rung_effective": RUNG_CAP,
        "trigger_price": price, "level": watch.get("level"),
        "detail": detail, "price_path_past": path_past,
        "price_path_future": None, "crossing_ids": crossing_ids,
        "intent": watch.get("intent"),
        "idempotency_key": idempotency_key,
    }).execute().data or []
    fire = inserted[0] if inserted else {}
    _write_alert(
        client, kind="trigger", watch_id=watch.get("id"),
        family=watch.get("family"),
        title=f"Level watcher: {instrument} fired (Rung 1 alert)",
        body=_alert_body(watch, instrument=instrument, price=price,
                         detail=detail, crossing_ids=crossing_ids,
                         now=now),
        evidence={"fire_id": fire.get("id"), "instrument": instrument,
                  "trigger_price": price, "detail": detail,
                  "crossing_ids": crossing_ids},
        now=now)
    return fire


def _alert_body(watch: dict, *, instrument: str, price: float,
                detail: dict, crossing_ids: list | None,
                now: datetime) -> str:
    when = now.astimezone(ET).strftime("%a %Y-%m-%d %H:%M ET")
    if crossing_ids:
        return (f"{instrument}: Spec C logged a band crossing from the "
                f"watcher's intraday read ({len(crossing_ids)} crossing "
                f"row(s)) at {when}. Rung 1 alert — Stage 1 places "
                f"nothing; the crossing log on the Guidance page carries "
                f"the would-be action and its Portfolio Check outcome.")
    trig = detail.get("trigger") or {}
    level = watch.get("level")
    level_txt = f" through {level}" if level is not None else ""
    return (f"{instrument} {trig.get('type')}{level_txt} — latest trade "
            f"{price} at {when}. Watch: {watch.get('name')}. Rung 1 "
            f"alert — Stage 1 places nothing; evidence is in the "
            f"trigger log.")


# ── the governor (framework; numbers are Kevin's, never placeholders) ───────

def evaluate_governor(group: dict, day_pnl: float | None) -> dict:
    """The disarm decision, pure. The spec's placeholder defaults
    (2x/3x unit) are NOT shipped: with either number unset there is no
    governor to trip, whatever the P&L. With numbers set but no P&L
    source (Stage 1 has no fills) the governor cannot trip either —
    it reports why instead of pretending."""
    target = group.get("daily_profit_target_usd")
    stop = group.get("daily_loss_stop_usd")
    if target is None or stop is None:
        return {"disarm": False, "reason": "numbers_not_set",
                "numbers_set": False}
    if day_pnl is None:
        return {"disarm": False, "reason": "no_pnl_source",
                "numbers_set": True}
    if day_pnl >= float(target):
        return {"disarm": True, "reason": "profit_target_hit",
                "numbers_set": True}
    if day_pnl <= -abs(float(stop)):
        return {"disarm": True, "reason": "loss_stop_hit",
                "numbers_set": True}
    return {"disarm": False, "reason": "within_bounds",
            "numbers_set": True}


def _governor_pass(client, *, now: datetime, pnl_reader) -> set[str]:
    """Evaluate every governor group for today's session; disarm +
    stand-down alert on a trip. Returns the set of disarmed groups
    (including groups disarmed earlier today — the disarm holds for
    the session)."""
    session = session_date_of(now)
    disarmed: set[str] = set()
    for state in _rows(client, GOV_STATE,
                       filters={"session_date": session}):
        if state.get("disarmed"):
            disarmed.add(state["group_name"])
    for group in _rows(client, GOV_GROUPS):
        name = group["name"]
        if name in disarmed:
            continue
        pnl = pnl_reader(name, session) if pnl_reader else None
        decision = evaluate_governor(group, pnl)
        if not decision["disarm"]:
            continue
        client.table(GOV_STATE).insert({
            "group_name": name, "session_date": session,
            "disarmed": True, "reason": decision["reason"],
            "day_pnl_usd": pnl, "updated_at": now.isoformat(),
        }).execute()
        _write_alert(
            client, kind="governor_stand_down",
            title=f"Governor stand-down: {name}",
            body=(f"Governor group {name} hit its "
                  f"{decision['reason'].replace('_', ' ')} "
                  f"(day P&L {pnl}) and is disarmed until the next "
                  f"session. Its watches will not fire today."),
            evidence={"group": name, "reason": decision["reason"],
                      "day_pnl_usd": pnl}, now=now)
        disarmed.add(name)
    return disarmed


# ── the tick ─────────────────────────────────────────────────────────────────

def run_tick(client, *, now: datetime | None = None, feed=None,
             pnl_reader=None, bc_readers: dict | None = None) -> dict:
    """One watcher evaluation cycle. Stateless: the armed set, the
    day's fires, governor state and band state are all re-read from
    the store, so this is safe to run every minute and after any
    restart. Outside market hours it exits fast (no evaluation, no
    heartbeat) — heartbeats exist to prove life during the session."""
    now = now or datetime.now(timezone.utc)
    feed = feed or AlpacaFeed()
    summary: dict = {"market_hours": is_market_hours(now), "fired": [],
                     "suppressed": [], "evaluated": [], "band": None,
                     "heartbeat": False, "down_alert": False,
                     "paths_backfilled": 0}
    if not summary["market_hours"]:
        return summary

    session = session_date_of(now)

    # Down detection first (the outage record), then this tick's beat.
    summary["down_alert"] = check_down_alert(client, now=now)
    last_hb = _last_heartbeat(client)
    if last_hb is None or now - last_hb >= HEARTBEAT_EVERY:
        client.table(HEARTBEATS).insert({
            "at": now.isoformat(), "session_date": session,
            "note": "tick"}).execute()
        summary["heartbeat"] = True

    summary["paths_backfilled"] = _backfill_paths(client, feed=feed,
                                                  now=now)

    disarmed = _governor_pass(client, now=now, pnl_reader=pnl_reader)

    watches = [w for w in _rows(client, WATCHES) if w.get("enabled")]
    band_watch = None
    for w in watches:
        if _parse_ts(w.get("expires_at")) is not None \
                and _parse_ts(w.get("expires_at")) <= now:
            continue  # expired
        if w.get("kind") == "band_crossing":
            band_watch = band_watch or w
            continue
        if w.get("governor_group") in disarmed:
            summary["suppressed"].append(
                {"watch_id": w.get("id"), "reason": "governor_disarmed"})
            continue
        if not w.get("allow_multi_fire") \
                and _fired_today(client, w.get("id"), session):
            continue  # the day's fire already exists — idempotent
        instrument = w.get("instrument")
        try:
            bars_all = feed.bars_today(instrument, now)
            price = float(feed.latest_trade(instrument))
        except Exception as exc:  # noqa: BLE001 -- named, never a fire
            summary["suppressed"].append(
                {"watch_id": w.get("id"),
                 "reason": f"feed_unavailable: {type(exc).__name__}"})
            continue
        bars = completed_bars(bars_all, now)
        conds = w.get("conditions") or {}
        baseline = None
        if conds.get("volume_multiple") is not None and bars:
            baseline = baseline_median_volume(
                client, feed, instrument,
                bars[-1]["t"].strftime("%H:%M"), session, now)
        t1 = bc.t1_classification(client, instrument) \
            if conds.get("file_state") else None
        fired, detail = check_conditions(
            w, bars=bars, price=price, now=now,
            baseline_volume=baseline, t1=t1)
        summary["evaluated"].append({"watch_id": w.get("id"),
                                     "detail": detail})
        if not fired:
            continue
        key = f"{w.get('id')}:{session}"
        if w.get("allow_multi_fire"):
            key += f":{now.astimezone(ET).strftime('%H%M')}"
        fire = _fire(client, w, now=now, instrument=instrument,
                     price=price, detail=detail,
                     path_past=_path_window(bars_all, now, 5),
                     crossing_ids=None, idempotency_key=key)
        summary["fired"].append(fire)

    if band_watch is not None:
        summary["band"] = _band_step(client, band_watch, feed=feed,
                                     now=now, bc_readers=bc_readers)
        summary["fired"].extend(summary["band"].pop("fires", []))
    return summary


def _band_step(client, watch: dict, *, feed, now: datetime,
               bc_readers: dict | None) -> dict:
    """Observe intraday zones on banded names; where a zone moved vs
    Spec C's stored state, drive Spec C's evaluation at the live
    price and alert from the crossings it logs. No second detector:
    without a stored baseline state there is nothing to compare, and
    C's scans own baselining."""
    from tradehub.valuation import store as val_store

    moved: dict[str, float] = {}
    snapshots: dict[str, object] = {}
    for sheet in val_store.latest_sheets(client):
        if sheet.get("status") != "banded" or not sheet.get("bands"):
            continue
        ticker = sheet["ticker"]
        states = _rows(client, bc.STATE, filters={"ticker": ticker})
        if not states:
            continue  # no baseline state for this name yet
        try:
            price = float(feed.latest_trade(ticker))
        except Exception:  # noqa: BLE001 -- an unreadable name is skipped
            continue
        live_zone = bc.zone_of(price, sheet["bands"])
        if any(s.get("zone") != live_zone for s in states):
            moved[ticker] = price
            snapshots[ticker] = sheet.get("snapshot_id")
    out: dict = {"moved": sorted(moved), "crossings_written": 0}
    if not moved:
        return out
    result = bc.run_watcher_evaluation(client, prices=moved, now=now,
                                       **(bc_readers or {}))
    out["evaluation"] = {k: result.get(k) for k in
                         ("ran", "reason", "crossings_written")}
    by_ticker: dict[str, list[dict]] = {}
    for row in result.get("crossings") or []:
        by_ticker.setdefault(row["ticker"], []).append(row)
    session = session_date_of(now)
    for ticker, rows in by_ticker.items():
        ids = [r.get("id") for r in rows]
        detail = {"via": "band_crossing",
                  "actions": [r.get("action") for r in rows],
                  "books": [r.get("book") for r in rows],
                  "zone": rows[0].get("zone"),
                  "band_snapshot_id": snapshots.get(ticker)}
        fire = _fire(client, watch, now=now, instrument=ticker,
                     price=moved[ticker], detail=detail,
                     path_past=None, crossing_ids=ids,
                     idempotency_key=(f"{watch.get('id')}:{session}:"
                                      f"{ticker}:{rows[0].get('action')}"
                                      f":{ids[0]}"))
        out.setdefault("fires", []).append(fire)
    out["crossings_written"] = result.get("crossings_written", 0)
    return out


def _backfill_paths(client, *, feed, now: datetime) -> int:
    """Fill the +5-minute price path on recent fires once it exists
    (the path after the trigger cannot be known at fire time)."""
    written = 0
    cutoff = now - timedelta(days=1)
    for fire in _rows(client, FIRES, order="id", desc=True, limit=100):
        if fire.get("price_path_future") is not None:
            continue
        fired_at = _parse_ts(fire.get("fired_at"))
        if fired_at is None or fired_at > now - timedelta(minutes=5) \
                or fired_at < cutoff:
            continue
        try:
            bars = feed.bars_between(fire["instrument"], fired_at,
                                     fired_at + timedelta(minutes=5))
        except Exception:  # noqa: BLE001 -- a failed pull defers the fill
            continue
        client.table(FIRES).update({
            "price_path_future": _path_window(
                bars, fired_at + timedelta(minutes=5), 5),
        }).eq("id", fire["id"]).execute()
        written += 1
    return written


# ── grading + automatic demotion ─────────────────────────────────────────────

def forward_return(closes, entry_date: str, horizon: int) -> float | None:
    """Close-to-close return h sessions after the entry session's
    close (daily closes, the band-grading convention). None when the
    window is immature."""
    import pandas as pd

    closes = closes.dropna().sort_index()
    pos = closes.index.get_indexer([pd.Timestamp(entry_date)],
                                   method="pad")
    if len(pos) == 0 or pos[0] < 0 or pos[0] + horizon >= len(closes):
        return None
    pos = int(pos[0])
    p0 = float(closes.iloc[pos])
    ph = float(closes.iloc[pos + horizon])
    if p0 <= 0:
        return None
    return ph / p0 - 1.0


def grade_fires(client, ds, *, now: datetime | None = None) -> dict:
    """One grading pass over the trigger log (frozen): fill ret/score
    at +1/+5 sessions on level-watch fires (the counterfactual is no
    action = 0, so the score is the intent-signed return; +5
    governs). Intent-'none' fires get raw returns only. Band-watch
    fires are graded by Spec C's falsifier, not here. Then the
    demotion rule: a family with >= DEMOTION_GATE graded triggers and
    a negative mean score_5 demotes one rung — at Stage 1 that means
    its watches auto-disable, once, latched, with an alert. There is
    no auto-promotion path."""
    now = now or datetime.now(timezone.utc)
    check_down_alert(client, now=now)
    rows = _rows(client, FIRES)
    graded = 0
    frames: dict[str, object] = {}
    for fire in rows:
        if fire.get("crossing_ids"):
            continue  # Spec C's population; its falsifier grades it
        need = [h for h in (1, 5) if fire.get(f"ret_{h}") is None]
        if not need:
            continue
        ticker = fire["instrument"]
        if ticker not in frames:
            try:
                frames[ticker] = ds.prices([ticker], years=3)
            except Exception:  # noqa: BLE001 -- a failed pull defers
                frames[ticker] = None
        frame = frames[ticker]
        if frame is None or ticker not in frame.columns:
            continue
        closes = frame[ticker].dropna()
        patch: dict = {}
        for h in need:
            r = forward_return(closes, str(fire.get("session_date")), h)
            if r is None:
                continue
            patch[f"ret_{h}"] = round(r, 6)
            if fire.get("intent") in ("long", "short"):
                sign = 1.0 if fire["intent"] == "long" else -1.0
                patch[f"score_{h}"] = round(sign * r, 6)
        if patch:
            patch["graded_at"] = now.isoformat()
            client.table(FIRES).update(patch) \
                .eq("id", fire["id"]).execute()
            fire.update(patch)
            graded += 1

    demoted: list[str] = []
    families = sorted({r.get("family") for r in rows
                       if r.get("family") and not r.get("crossing_ids")})
    for family in families:
        sample = [r for r in rows
                  if r.get("family") == family
                  and not r.get("crossing_ids")
                  and r.get("score_5") is not None]
        scores = [float(r["score_5"]) for r in sample]
        mean = round(statistics.fmean(scores), 6) if scores else None
        state_rows = _rows(client, FAMILY_STATE,
                           filters={"family": family})
        state = state_rows[0] if state_rows else None
        patch = {"graded_count": len(scores), "mean_score_5": mean,
                 "updated_at": now.isoformat()}
        if state is None:
            client.table(FAMILY_STATE).insert(
                {"family": family, **patch}).execute()
            state = {"demoted_at": None}
        else:
            client.table(FAMILY_STATE).update(patch) \
                .eq("family", family).execute()
        if len(scores) >= DEMOTION_GATE and mean is not None and mean < 0 \
                and not state.get("demoted_at"):
            for w in _rows(client, WATCHES,
                           filters={"family": family}):
                if w.get("enabled"):
                    client.table(WATCHES).update({
                        "enabled": False,
                        "disabled_reason": "auto_demotion",
                        "updated_at": now.isoformat(),
                    }).eq("id", w["id"]).execute()
            client.table(FAMILY_STATE).update(
                {"demoted_at": now.isoformat()}) \
                .eq("family", family).execute()
            _write_alert(
                client, kind="demotion", family=family,
                title=f"Rule family demoted: {family}",
                body=(f"Family {family} reached {len(scores)} graded "
                      f"triggers with a negative mean +5-session score "
                      f"({mean}); per the frozen rule it demotes one "
                      f"rung — at Stage 1 its watches are auto-disabled. "
                      f"Re-arming is Kevin's call; nothing promotes "
                      f"automatically."),
                evidence={"family": family, "graded_count": len(scores),
                          "mean_score_5": mean}, now=now)
            demoted.append(family)
    return {"fires_seen": len(rows), "graded": graded, "demoted": demoted}


# ── the read surface ─────────────────────────────────────────────────────────

def read_surface(client, *, now: datetime | None = None,
                 limit: int = 50) -> dict:
    """The Guidance page's Level Watcher payload: stage and rung cap
    up front (never implied), watcher health, the watches, the
    trigger log, pending alerts, family grading, and the governor
    state — with the CPI blackout gap carried on the payload so it is
    visible wherever the watcher is shown."""
    now = now or datetime.now(timezone.utc)
    session = session_date_of(now)
    watches = _rows(client, WATCHES, order="id", desc=True, limit=limit)
    groups = _rows(client, GOV_GROUPS)
    by_name = {g["name"]: g for g in groups}
    for w in watches:
        if w.get("governor_group"):
            by_name.setdefault(w["governor_group"],
                               {"name": w["governor_group"]})
    states = {s["group_name"]: s for s in _rows(
        client, GOV_STATE, filters={"session_date": session})}
    governors = []
    for name in sorted(by_name):
        g = by_name[name]
        numbers_set = g.get("daily_profit_target_usd") is not None \
            and g.get("daily_loss_stop_usd") is not None
        state = states.get(name) or {}
        if not numbers_set:
            note = ("Governor numbers not set — Kevin's to set; this "
                    "group has no active governor.")
        elif state.get("disarmed"):
            note = f"Disarmed for this session ({state.get('reason')})."
        else:
            note = ("Numbers set; no P&L source at Rung 1, so the "
                    "governor cannot trip in Stage 1.")
        governors.append({
            "name": name, "numbers_set": numbers_set,
            "standard_unit_usd": g.get("standard_unit_usd"),
            "daily_profit_target_usd": g.get("daily_profit_target_usd"),
            "daily_loss_stop_usd": g.get("daily_loss_stop_usd"),
            "disarmed": bool(state.get("disarmed")),
            "reason": state.get("reason"), "note": note})
    return {
        "stage": STAGE, "rung_cap": RUNG_CAP,
        "mode": "rung1_alerts_only",
        "cpi_blackout_gap": True,
        "status": watcher_status(client, now=now),
        "watches": watches,
        "fires": _rows(client, FIRES, order="id", desc=True, limit=limit),
        "alerts_pending": _rows(client, ALERTS,
                                filters={"status": "pending"},
                                order="id", desc=True, limit=limit),
        "alerts_recent": _rows(client, ALERTS, order="id", desc=True,
                               limit=limit),
        "families": _rows(client, FAMILY_STATE, order="family"),
        "governors": governors,
    }
