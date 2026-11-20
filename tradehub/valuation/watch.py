"""The section 5 cadence: a continuous band watch over held positions and
covered names, event triggers queued by the frozen priority, and on-demand
renders drained against the shared daily debate budget.

Flags are flags — this module never places, suggests, or sizes an order.
A held name whose price has drifted above its top band raises a
potential-sell flag; a held name sitting inside (or below) its bands is a
comfortable hold. Crossings and falsifier windows are priority 1, new
guidance priority 2, refreshes priority 3 (on-demand renders bypass the
queue entirely and are not triggers).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from tradehub.portfolio.options import parse_occ
from tradehub.valuation import store as val_store
from tradehub.valuation import verdict_store, verdicts

logger = logging.getLogger(__name__)

BOOKS = ("main", "big")
PRIORITY = {"crossing": 1, "falsifier_window": 1, "new_guidance": 2,
            "refresh": 3}
_DIRECTIONAL = ("buy_zone", "buy_zone_strong", "short_zone",
                "short_zone_strong")
PRINT_WINDOW_DAYS = 5
# One debate per ticker per window: a rendered crossing/refresh re-fire inside
# this window is the same call, not a new one (no new state column/migration).
TRIGGER_COOLDOWN_HOURS = 24


def underlying(symbol: str) -> str:
    """A held symbol's underlying: the OCC root for options, itself for
    shares."""
    try:
        return parse_occ(symbol)["underlying"]
    except Exception:  # noqa: BLE001 -- not an OCC symbol: it is the underlying
        return symbol


def band_relation(price: float, bands: dict) -> str:
    if price > float(bands["bull"]):
        return "above_bull"
    if price < float(bands["bear"]):
        return "below_bear"
    return "inside_bands"


def flag_for(price: float, bands: dict) -> tuple[str, str]:
    relation = band_relation(price, bands)
    if relation == "above_bull":
        return "potential_sell", relation
    return "comfortable_hold", relation


def _default_positions(book: str) -> dict:
    from tradehub.portfolio.option_orders import positions_map

    return positions_map(book)


def _created_at(trigger: dict) -> datetime | None:
    """Parse a trigger's created_at, assuming UTC when the stamp is naive."""
    try:
        stamp = datetime.fromisoformat(trigger["created_at"])
    except (KeyError, TypeError, ValueError):
        return None
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def _refire_reason(client, ticker: str, kind: str, detail: dict,
                   now: datetime) -> str | None:
    """Why this re-fire is the same call as an already-rendered trigger."""
    past = verdict_store.recent_triggers(client, ticker, kind)
    if kind == "falsifier_window":
        print_date = detail.get("print_date")
        if print_date and any((t.get("detail") or {}).get("print_date") ==
                              print_date for t in past):
            return "same print_date"
    elif kind == "new_guidance":
        recorded_at = detail.get("recorded_at")
        if recorded_at and any((t.get("detail") or {}).get("recorded_at") ==
                               recorded_at for t in past):
            return "same recorded_at"
    elif kind in ("crossing", "refresh"):
        cutoff = now - timedelta(hours=TRIGGER_COOLDOWN_HOURS)
        for t in past:
            stamp = _created_at(t)
            if stamp is not None and stamp >= cutoff:
                return f"within {TRIGGER_COOLDOWN_HOURS}h cooldown"
    return None


def _queue_trigger(client, ticker: str, kind: str, detail: dict,
                   now: datetime) -> str:
    """Queue a trigger unless a pending twin exists or a rendered one already
    covers this window. Returns 'queued', 'suppressed' or 'skipped'."""
    for pending in verdict_store.pending_triggers(client):
        if pending["ticker"] == ticker and pending["kind"] == kind:
            return "skipped"
    reason = _refire_reason(client, ticker, kind, detail, now)
    if reason:
        logger.info("valuation watch: suppressed %s re-fire for %s (%s)",
                    kind, ticker, reason)
        return "suppressed"
    verdict_store.insert_trigger(client, {
        "ticker": ticker, "kind": kind, "priority": PRIORITY[kind],
        "state": "pending", "created_at": now.isoformat(), "detail": detail})
    return "queued"


def _crossed_band(prev_price: float, price: float, bands: dict) -> str | None:
    for name in ("bear", "base", "bull"):
        level = float(bands[name])
        if (prev_price - level) * (price - level) < 0 or \
                (prev_price <= level < price) or (price <= level < prev_price):
            return name
    return None


def _next_print_in_window(ds, ticker: str, now: datetime, days: int
                          ) -> date | None:
    """The next earnings print date inside the window, or None — the
    falsifier's calendar proxy (the falsifier itself is prose)."""
    try:
        frame = ds.earnings_dates(ticker)
        if frame is None or not len(frame):
            return None
        today = now.date()
        hits = []
        for stamp in frame.index:
            day = stamp.date() if hasattr(stamp, "date") else stamp
            if today <= day and (day - today).days <= days:
                hits.append(day)
        return min(hits) if hits else None
    except Exception:  # noqa: BLE001 -- no calendar is no trigger, not a crash
        return None


def _print_within(ds, ticker: str, now: datetime, days: int) -> bool:
    """True when the name's next earnings print lands inside the window."""
    return _next_print_in_window(ds, ticker, now, days) is not None


def compute_watch(client, ds, *, positions_fn=None, now: datetime | None = None
                  ) -> dict:
    """One watch pass: held-position flags for both books + trigger
    detection over every banded, unstale sheet. Persists watch state and any
    new triggers; returns the flags and what was queued."""
    now = now or datetime.now(timezone.utc)
    positions_fn = positions_fn or _default_positions
    sheets = {s["ticker"]: s for s in val_store.latest_sheets(client)
              if s.get("status") == "banded" and not s.get("stale")
              and s.get("bands") and s.get("price") is not None}

    flags: list[dict] = []
    for book in BOOKS:
        try:
            held = positions_fn(book) or {}
        except Exception:  # noqa: BLE001 -- an unreadable book flags nothing
            held = {}
        for symbol, qty in sorted(held.items()):
            if not qty:
                continue
            name = underlying(symbol)
            sheet = sheets.get(name)
            if sheet is None:
                continue
            flag, detail = flag_for(float(sheet["price"]), sheet["bands"])
            flags.append({"book": book, "symbol": symbol,
                          "underlying": name, "flag": flag, "detail": detail,
                          "price": sheet["price"], "bands": sheet["bands"]})
            verdict_store.set_watch_state(client, {
                "key": f"held:{book}:{symbol}", "kind": "held",
                "ticker": name,
                "state": {"flag": flag, "detail": detail, "book": book,
                          "symbol": symbol, "underlying": name,
                          "price": sheet["price"], "bands": sheet["bands"]},
                "updated_at": now.isoformat()})

    records = val_store.all_records(client)
    latest_guide = {t: max((r.get("created_at") or "") for r in rows)
                    for t, rows in records.items() if rows}
    queued = 0
    suppressed = 0

    def _enqueue(ticker, kind, detail):
        nonlocal queued, suppressed
        outcome = _queue_trigger(client, ticker, kind, detail, now)
        if outcome == "queued":
            queued += 1
        elif outcome == "suppressed":
            suppressed += 1

    for ticker, sheet in sorted(sheets.items()):
        key = f"ticker:{ticker}"
        prev = verdict_store.watch_state(client, key)
        zone = sheet.get("baseline_verdict")
        price = float(sheet["price"])
        if prev is not None:
            prev_price = prev.get("price")
            crossed = (_crossed_band(float(prev_price), price, sheet["bands"])
                       if prev_price is not None else None)
            zone_entry = zone in _DIRECTIONAL and prev.get("zone") != zone
            if crossed or zone_entry:
                _enqueue(ticker, "crossing",
                         {"band": crossed, "from_zone": prev.get("zone"),
                          "to_zone": zone, "price": price})
            guide_at = latest_guide.get(ticker)
            if guide_at and prev.get("last_guide_at") and \
                    guide_at > prev["last_guide_at"]:
                _enqueue(ticker, "new_guidance", {"recorded_at": guide_at})
        print_date = _next_print_in_window(ds, ticker, now, PRINT_WINDOW_DAYS)
        if print_date is not None:
            _enqueue(ticker, "falsifier_window",
                     {"within_days": PRINT_WINDOW_DAYS,
                      "print_date": print_date.isoformat()})
        verdict_store.set_watch_state(client, {
            "key": key, "kind": "ticker", "ticker": ticker, "zone": zone,
            "price": price, "last_guide_at": latest_guide.get(ticker),
            "updated_at": now.isoformat()})
    return {"flags": flags, "triggers_queued": queued,
            "triggers_suppressed": suppressed}


def drain_triggers(client, ds, *, chat=None, seat=None,
                   now: datetime | None = None) -> list[dict]:
    """Render pending triggers in priority order until the queue empties or
    the daily budget does (the rest stay pending for the next pass)."""
    now = now or datetime.now(timezone.utc)
    rendered: list[dict] = []
    for trig in verdict_store.pending_triggers(client):
        result = verdicts.render_verdict(client, ds, trig["ticker"],
                                         trigger=trig["kind"], chat=chat,
                                         seat=seat, now=now)
        if result["status"] == "cap_reached":
            break
        if result["status"] in ("rendered", "void"):
            row = result.get("verdict_row") or {}
            verdict_store.mark_trigger(client, trig["id"], "done",
                                       verdict_id=row.get("id"))
        else:
            verdict_store.mark_trigger(client, trig["id"], "failed")
        rendered.append({**result, "trigger_id": trig["id"]})
    return rendered
