"""Guidance rebuild, wired alerts (Kevin-approved brief, 2026-11-16):
HELD names only. When a held name's snapshot-to-snapshot move crosses
into the buy zone, or breaks below its bear band, this bridge arms a
Level Watcher watch on the crossed level and opens a manual action in
the existing review flow — no new alerting stack: the watch is a plain
level_watches row the watcher tick already evaluates, and the action
goes through workshop store.add_manual_action with its own dedupe.

Distinct from Spec C on purpose: band_crossing.py is a log-only
falsifier engine whose rows never reach manual_actions (frozen); this
bridge is the page's alert wiring, with its own manual-action kind
("band_crossing_review") so band crossings never blend with the
tracker PR 6 kill-line exit reviews ("exit_review"). Detection is a
transition between the two latest COMPLETED snapshots' band history —
a first sighting (no previous row) is not a crossing, exactly Spec C's
rule. Re-runs over the same snapshot pair are no-ops: the watch arming
dedupes on (family, instrument, level) among enabled watches and the
manual-action store dedupes on the open (book, kind, symbol) row.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradehub.valuation import band_crossing as bc
from tradehub.valuation import candidates as cand
from tradehub.valuation import page_summary
from tradehub.valuation import store as val_store
from tradehub.workshop import store as workshop_store

FAMILY = "guidance_band"
ACTION_KIND = "band_crossing_review"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bands(row: dict) -> dict | None:
    if row.get("bear") is None:
        return None
    return {"bear": _num(row.get("bear")), "base": _num(row.get("base")),
            "bull": _num(row.get("bull"))}


def detect_crossings(latest_hist: list[dict], prev_hist: list[dict],
                     held: dict) -> list[dict]:
    """Held-name crossings between two snapshots' band-history rows.
    Pure. Each item: {ticker, kind, level, price, books} where kind is
    'entered_buy_zone' (previous zone bull/above_bull, latest zone
    bear/base — Spec C's zone table on each snapshot's own price and
    bands) or 'broke_below_bear' (previous price above the previous
    bear band, latest price at or below the latest bear band). A name
    with no previous banded row has nothing to transition from."""
    before = {r.get("ticker"): r for r in prev_hist if r.get("ticker")}
    out: list[dict] = []
    for row in latest_hist:
        ticker = row.get("ticker")
        if not ticker or ticker not in held:
            continue
        old = before.get(ticker)
        bands, old_bands = _bands(row), _bands(old) if old else None
        if bands is None or old_bands is None:
            continue
        price, old_price = _num(row.get("price")), _num(old.get("price"))
        if price is None or old_price is None:
            continue
        zone = bc.zone_of(price, bands)
        old_zone = bc.zone_of(old_price, old_bands)
        books = (held.get(ticker) or {}).get("books", [])
        if old_zone in ("bull", "above_bull") and zone in ("bear", "base"):
            out.append({"ticker": ticker, "kind": "entered_buy_zone",
                        "level": bands["base"], "price": price,
                        "books": books})
        if old_price > old_bands["bear"] and price <= bands["bear"]:
            out.append({"ticker": ticker, "kind": "broke_below_bear",
                        "level": bands["bear"], "price": price,
                        "books": books})
    return out


def _watch_armed(client, ticker: str, level: float) -> bool:
    rows = (client.table("level_watches").select("id, level, enabled")
            .eq("family", FAMILY).eq("instrument", ticker)
            .execute().data) or []
    # enabled defaults to true in the schema; a row without the flag
    # (test fakes) reads as enabled, matching the default.
    return any(_num(r.get("level")) == level
               and r.get("enabled") in (None, True) for r in rows)


def arm_watch(client, crossing: dict, *, snapshot_id, now: datetime) -> bool:
    """Insert the level watch for one crossing unless an enabled watch
    on the same level already exists. Returns True when a watch was
    created."""
    ticker, level = crossing["ticker"], crossing["level"]
    if _watch_armed(client, ticker, level):
        return False
    label = ("entered the buy zone (base band)" if crossing["kind"]
             == "entered_buy_zone" else "broke below the bear band")
    client.table("level_watches").insert({
        "name": f"{ticker} guidance band — {crossing['kind']}",
        "family": FAMILY, "kind": "level", "instrument": ticker,
        "trigger_type": "cross", "level": level,
        "intent": "alert", "rung": 1, "book": None,
        "conditions": {"source": "guidance_alerts",
                       "crossing": crossing["kind"],
                       "snapshot_id": snapshot_id,
                       "price_at_crossing": crossing["price"]},
        "note": (f"Held name {label} between completed valuation "
                 f"snapshots; armed by the Guidance page alert wiring "
                 f"(2026-11-16 brief). Alert only — no order path."),
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }).execute()
    return True


def run_alerts(client, *, positions_fn=None,
               now: datetime | None = None) -> dict:
    """One bridge pass over the two latest completed snapshots. Arms a
    watch per held-name crossing and opens one manual action per held
    book. Returns counts; with fewer than two completed snapshots there
    is nothing to compare and the pass says so."""
    now = now or datetime.now(timezone.utc)
    snap = val_store.latest_snapshot(client)
    prev = page_summary.previous_snapshot(client) if snap else None
    if snap is None or prev is None:
        return {"ran": False, "reason": "needs two completed snapshots",
                "crossings": [], "watches_armed": 0, "actions_opened": 0}
    latest_hist = val_store.snapshot_history(client, snap["id"])
    prev_hist = val_store.snapshot_history(client, prev["id"])
    held = cand.held_positions(client, positions_fn) or {}
    crossings = detect_crossings(latest_hist, prev_hist, held)
    armed = 0
    opened = 0
    for crossing in crossings:
        if arm_watch(client, crossing, snapshot_id=snap["id"], now=now):
            armed += 1
        label = ("entered the buy zone" if crossing["kind"]
                 == "entered_buy_zone" else "broke below the bear band")
        detail = (f"{crossing['ticker']} {label}: price "
                  f"{crossing['price']} vs band level {crossing['level']} "
                  f"(snapshot {prev['id']} -> {snap['id']}). Review the "
                  f"position against the Guidance bands.")
        for book in crossing["books"]:
            rows = (client.table("manual_actions").select("id, state")
                    .eq("book", book).eq("kind", ACTION_KIND)
                    .eq("symbol", crossing["ticker"])
                    .is_("idea_id", "null")
                    .execute().data) or []
            # state defaults to 'open' in the schema; a row without a
            # state (test fakes) reads as open, matching the default.
            if any(r.get("state") in (None, "open") for r in rows):
                continue  # the store's dedupe would swallow it anyway
            workshop_store.add_manual_action(
                client, book, None, ACTION_KIND, crossing["ticker"],
                detail)
            opened += 1
    return {"ran": True, "crossings": crossings,
            "watches_armed": armed, "actions_opened": opened}
