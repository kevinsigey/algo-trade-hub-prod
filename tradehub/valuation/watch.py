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

from datetime import datetime, timezone

from tradehub.portfolio.options import parse_occ
from tradehub.valuation import store as val_store
from tradehub.valuation import verdict_store, verdicts

BOOKS = ("main", "big")
PRIORITY = {"crossing": 1, "falsifier_window": 1, "new_guidance": 2,
            "refresh": 3}
_DIRECTIONAL = ("buy_zone", "buy_zone_strong", "short_zone",
                "short_zone_strong")
PRINT_WINDOW_DAYS = 5


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


def _queue_trigger(client, ticker: str, kind: str, detail: dict,
                   now: datetime) -> bool:
    """Queue a trigger unless an identical one is already pending."""
    for pending in verdict_store.pending_triggers(client):
        if pending["ticker"] == ticker and pending["kind"] == kind:
            return False
    verdict_store.insert_trigger(client, {
        "ticker": ticker, "kind": kind, "priority": PRIORITY[kind],
        "state": "pending", "created_at": now.isoformat(), "detail": detail})
    return True


def _crossed_band(prev_price: float, price: float, bands: dict) -> str | None:
    for name in ("bear", "base", "bull"):
        level = float(bands[name])
        if (prev_price - level) * (price - level) < 0 or \
                (prev_price <= level < price) or (price <= level < prev_price):
            return name
    return None


def _print_within(ds, ticker: str, now: datetime, days: int) -> bool:
    """True when the name's next earnings print lands inside the window —
    the falsifier's calendar proxy (the falsifier itself is prose)."""
    try:
        frame = ds.earnings_dates(ticker)
        if frame is None or not len(frame):
            return False
        today = now.date()
        for stamp in frame.index:
            day = stamp.date() if hasattr(stamp, "date") else stamp
            if today <= day and (day - today).days <= days:
                return True
    except Exception:  # noqa: BLE001 -- no calendar is no trigger, not a crash
        return False
    return False


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
                if _queue_trigger(client, ticker, "crossing",
                                  {"band": crossed, "from_zone":
                                   prev.get("zone"), "to_zone": zone,
                                   "price": price}, now):
                    queued += 1
            guide_at = latest_guide.get(ticker)
            if guide_at and prev.get("last_guide_at") and \
                    guide_at > prev["last_guide_at"]:
                if _queue_trigger(client, ticker, "new_guidance",
                                  {"recorded_at": guide_at}, now):
                    queued += 1
        if _print_within(ds, ticker, now, PRINT_WINDOW_DAYS):
            if _queue_trigger(client, ticker, "falsifier_window",
                              {"within_days": PRINT_WINDOW_DAYS}, now):
                queued += 1
        verdict_store.set_watch_state(client, {
            "key": key, "kind": "ticker", "ticker": ticker, "zone": zone,
            "price": price, "last_guide_at": latest_guide.get(ticker),
            "updated_at": now.isoformat()})
    return {"flags": flags, "triggers_queued": queued}


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
