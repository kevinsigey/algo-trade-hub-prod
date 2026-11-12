"""Kalshi DEMO auto-trader for the 15-minute natural gas rule.

Kevin's build (approved 2026-11-11, sizing amended 2026-11-12): follow the
live gate's gated natural-gas buys from `fifteen_rule_decisions` with real
orders on the Kalshi DEMO account only, sized at 1% of the demo balance per
decision, scaling with the balance. Demo fills do not prove the edge; the
shadow record (the decisions table itself) is the measure.

Hard rules:
- Demo only, enforced in code: every run asserts the demo host through
  KalshiPortfolio.assert_demo_host() before any order call, and the only
  order-writing surface in tradehub/ is that guarded client.
- Only `KXNATGAS15M` buys stamped with the version fifteen_tracking
  ._live_gate() returns are traded -- never the blend shadow's rows,
  never another series, never a skip.
- One row per decision in `kalshi_demo_orders`; the (series, target)
  unique constraint is the never-order-twice guarantee.
- The live rule, the blend's frozen rows, shadow scoring and the Alpaca
  paper-order path are untouched: this module only reads them.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradehub import fifteen_tracking
from tradehub import oil_fifteen_rule as rule
from tradehub.core.kalshi_portfolio import NotDemoHostError
from tradehub.journal.kalshi_linked import ticker_of

SERIES = "KXNATGAS15M"
ORDERS = "kalshi_demo_orders"
DECISIONS = rule.DECISIONS_TABLE
TICKS = fifteen_tracking.TICKS_TABLE

CANCEL_BUFFER = timedelta(seconds=60)   # orders die one minute before the window closes
FRESHNESS = timedelta(minutes=20)       # a decision older than this is stale, never chased
ET = ZoneInfo("America/New_York")
SKIP_STATUSES = ("skipped_cap", "skipped_no_depth")
OPEN_STATUSES = ("pending", "resting", "filled")


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.isoformat()


# -- env caps (conservative defaults; Kevin's numbers to change) --------------

def budget_pct() -> float:
    return float(os.getenv("KALSHI_DEMO_BUDGET_PCT", "0.01"))


def max_contracts_per_day() -> int:
    return int(os.getenv("KALSHI_DEMO_MAX_CONTRACTS_PER_DAY", "100"))


def max_loss_per_day_usd() -> float:
    return float(os.getenv("KALSHI_DEMO_MAX_LOSS_PER_DAY_USD", "20"))


def size_contracts(balance_usd: float, price: float, pct: float) -> int:
    """Kevin's 1% rule: floor(balance x pct / price), minimum 1 contract.

    Price-only, as Kevin stated it: the taker fee adds ~0.8% on top at
    typical quotes, which the PR flags rather than silently correcting.
    """
    if price <= 0 or balance_usd <= 0:
        return 0
    return max(1, math.floor(balance_usd * pct / price))


# -- reads --------------------------------------------------------------------

def _select(supa, table: str, filters: dict, order: str | None = None,
            desc: bool = False, limit: int = 1000) -> list[dict]:
    query = supa.table(table).select("*")
    for col, val in filters.items():
        query = query.eq(col, val)
    if order:
        query = query.order(order, desc=desc)
    rows = query.limit(limit).execute().data or []
    return rows


def ask_size_at(supa, series: str, close_time: Any, side: str,
                now: datetime) -> int | None:
    """Contracts on offer at the side's ask from the minute tape: the
    latest tick at or before `now` for this window. None when the tape
    has no row (unknown depth is not a measured zero)."""
    ticks = _select(supa, TICKS, {"series": series, "close_time": _iso(_dt(close_time))})
    best = None
    for tick in ticks:
        at = tick.get("at")
        if at is None or _dt(at) > now:
            continue
        if best is None or _dt(at) > _dt(best["at"]):
            best = tick
    if best is None:
        return None
    size = best.get("yes_ask_size" if side == "yes" else "no_ask_size")
    return None if size is None else int(size)


def _day_start_et(now: datetime) -> datetime:
    return now.astimezone(ET).replace(hour=0, minute=0, second=0, microsecond=0)


# -- the pass -----------------------------------------------------------------

def run_once(supa, portfolio, now: datetime) -> dict[str, Any]:
    """One runner pass: reconcile open rows, then trade fresh gated buys.

    `portfolio` is a KalshiPortfolio (or a test fake with the same
    surface). All Kalshi order calls go through its demo-guarded methods.
    """
    summary: dict[str, Any] = {
        "gate_version": None, "candidates": 0, "other_gate_versions": 0,
        "placed": 0, "skipped_cap": 0, "skipped_no_depth": 0,
        "cancelled": 0, "settled": 0, "errors": [],
    }
    try:
        portfolio.assert_demo_host()
    except NotDemoHostError as exc:
        summary["refused"] = str(exc)
        return summary

    version, _since = fifteen_tracking._live_gate(supa)
    summary["gate_version"] = version

    rows = _select(supa, ORDERS, {}, order="created_at", desc=True, limit=500)
    by_target = {r["target"]: r for r in rows}

    _reconcile(supa, portfolio, rows, now, summary)

    # Fresh gated gas buys, stamped with the live gate's version only.
    decisions = _select(supa, DECISIONS, {"series": SERIES, "action": "buy"},
                        order="close_time", limit=1000)
    cutoff = now + CANCEL_BUFFER
    fresh = []
    for d in decisions:
        if d.get("gate_version") != version:
            summary["other_gate_versions"] += 1
            continue
        if _dt(d["close_time"]) <= cutoff or now - _dt(d["frozen_at"]) > FRESHNESS:
            continue
        fresh.append(d)
    summary["candidates"] = len(fresh)

    # Daily-cap state for the ET day, tracked in memory as this pass places.
    day_start = _day_start_et(now)
    todays = [r for r in rows if _dt(r["created_at"]) >= day_start]
    contracts_today = sum(int(r["contracts"]) for r in todays
                           if r["status"] not in SKIP_STATUSES)
    loss_used = 0.0
    for r in todays:
        if r["status"] == "settled" and (r.get("settlement_pnl") or 0) < 0:
            loss_used += -float(r["settlement_pnl"])
        elif r["status"] in ("resting", "filled"):
            filled = int(r.get("contracts_filled") or 0) or int(r["contracts"])
            price = r.get("fill_price") or r["limit_price"]
            loss_used += filled * float(price)

    pct = budget_pct()
    cap_contracts = max_contracts_per_day()
    cap_loss = max_loss_per_day_usd()

    for d in fresh:
        target = d["target"]
        existing = by_target.get(target)
        if existing is not None and existing["status"] != "pending":
            continue  # already traded or terminally skipped -- never twice
        cost = float(d["cost"])
        balance = _balance_usd(portfolio)
        if balance is None:
            summary["errors"].append("balance unavailable; placements paused this pass")
            break
        contracts = size_contracts(balance, cost, pct)
        base_row = {
            "series": SERIES, "target": target,
            "ticker": d.get("ticker") or ticker_of(target),
            "side": d["side"], "gate_version": version,
            "limit_price": cost, "frozen_quote": cost,
            "window_close": _iso(_dt(d["close_time"])),
            "client_order_id": f"kd-{d.get('ticker') or ticker_of(target)}",
        }
        depth = ask_size_at(supa, SERIES, d["close_time"], d["side"], now)
        if depth is not None and depth < 1:
            _skip(supa, existing, {**base_row, "contracts": 0, "ask_size": depth,
                                   "status": "skipped_no_depth"})
            summary["skipped_no_depth"] += 1
            continue
        if contracts_today >= cap_contracts:
            _skip(supa, existing, {**base_row, "contracts": 0, "ask_size": depth,
                                   "status": "skipped_cap",
                                   "skip_reason": "daily_contract_cap"})
            summary["skipped_cap"] += 1
            continue
        contracts = min(contracts, cap_contracts - contracts_today)
        if loss_used + contracts * cost > cap_loss:
            _skip(supa, existing, {**base_row, "contracts": 0, "ask_size": depth,
                                   "status": "skipped_cap",
                                   "skip_reason": "daily_loss_cap"})
            summary["skipped_cap"] += 1
            continue

        expires = _dt(d["close_time"]) - CANCEL_BUFFER
        claim = {**base_row, "contracts": contracts, "contracts_filled": 0,
                 "ask_size": depth, "balance_at_sizing": balance, "budget_pct": pct,
                 "expires_at": _iso(expires), "status": "pending"}
        row = existing or _insert(supa, claim, summary)
        if row is None:
            continue  # insert failed (unique backstop) -- already traded elsewhere
        try:
            order = portfolio.create_order(
                ticker=base_row["ticker"], side=d["side"], count=contracts,
                limit_price_cents=int(round(cost * 100)),
                client_order_id=base_row["client_order_id"],
                expiration_ts=int(expires.timestamp()))
        except Exception as exc:  # noqa: BLE001 -- leave pending; reconcile owns it
            summary["errors"].append(f"place {target}: {exc}")
            continue
        _update(supa, row, {"kalshi_order_id": order.get("order_id"),
                            "status": "resting", "contracts": contracts,
                            "balance_at_sizing": balance, "budget_pct": pct,
                            "ask_size": depth, "expires_at": _iso(expires)})
        contracts_today += contracts
        loss_used += contracts * cost
        summary["placed"] += 1
    return summary


def _balance_usd(portfolio) -> float | None:
    try:
        data = portfolio.get_balance()
    except Exception:  # noqa: BLE001
        return None
    if not data or data.get("balance") is None:
        return None
    return float(data["balance"]) / 100.0


def _insert(supa, row: dict, summary: dict) -> dict | None:
    try:
        data = supa.table(ORDERS).insert(row).execute().data
    except Exception as exc:  # noqa: BLE001 -- unique (series, target) backstop
        summary["errors"].append(f"claim {row['target']}: {exc}")
        return None
    return (data or [row])[0]


def _skip(supa, existing: dict | None, row: dict) -> None:
    if existing is not None:
        _update(supa, existing, {k: row[k] for k in
                                 ("status", "skip_reason", "ask_size", "contracts")
                                 if k in row})
    else:
        try:
            supa.table(ORDERS).insert(row).execute()
        except Exception:  # noqa: BLE001 -- a lost skip row never blocks the pass
            pass


def _update(supa, row: dict, patch: dict) -> None:
    patch = {**patch, "updated_at": _iso(datetime.now(timezone.utc))}
    supa.table(ORDERS).update(patch).eq("id", row["id"]).execute()
    row.update(patch)


# -- reconcile ----------------------------------------------------------------

def _fills_by_order(portfolio) -> dict[str, dict]:
    """order_id -> {count, avg_price (dollars, bought side), first_ts}."""
    out: dict[str, dict] = {}
    try:
        fills = portfolio.get_fills(limit=200)
    except Exception:  # noqa: BLE001
        return out
    for f in fills or []:
        oid = f.get("order_id")
        if not oid:
            continue
        count = float(f.get("count_fp") or f.get("count") or 0)
        if count <= 0:
            continue
        cents = f.get("yes_price") if f.get("side") == "yes" else f.get("no_price")
        if cents is None:
            cents = f.get("yes_price", 0)
        agg = out.setdefault(oid, {"count": 0.0, "cost": 0.0, "first_ts": None})
        agg["count"] += count
        agg["cost"] += float(cents) * count
        ts = f.get("created_ts")
        if ts and (agg["first_ts"] is None or ts < agg["first_ts"]):
            agg["first_ts"] = ts
    for agg in out.values():
        agg["avg_price"] = (agg["cost"] / agg["count"] / 100.0) if agg["count"] else None
    return out


def _reconcile(supa, portfolio, rows: list[dict], now: datetime,
               summary: dict) -> None:
    open_rows = [r for r in rows if r["status"] in OPEN_STATUSES]
    if not open_rows:
        return
    fills = _fills_by_order(portfolio)
    outcomes: dict[str, int | None] = {}
    settled_decisions = _select(supa, DECISIONS, {"series": SERIES},
                                 order="close_time", desc=True, limit=1000)
    for d in settled_decisions:
        outcomes[d["target"]] = d.get("outcome")

    for row in open_rows:
        close = _dt(row["window_close"])
        if row["status"] == "pending":
            if close - CANCEL_BUFFER <= now:
                _update(supa, row, {"status": "cancelled",
                                    "skip_reason": "placement_interrupted"})
                summary["cancelled"] += 1
            continue
        oid = row.get("kalshi_order_id")
        fill = fills.get(oid or "", {})
        # A row already marked filled in an earlier pass keeps its count
        # even after its fills age out of the fills endpoint's window.
        filled = max(int(fill.get("count") or 0),
                     int(row.get("contracts_filled") or 0))
        if filled > 0 and (int(row.get("contracts_filled") or 0) != filled
                           or row.get("fill_price") is None):
            _update(supa, row, {
                "contracts_filled": filled,
                "fill_price": row.get("fill_price") or fill.get("avg_price"),
                "filled_at": fill.get("first_ts") or _iso(now), "status": "filled"})
        outcome = outcomes.get(row["target"])
        if outcome is not None and filled > 0:
            pnl = round(filled * rule.pnl(row["side"], float(row.get("fill_price")
                        or fill.get("avg_price") or row["limit_price"]),
                        int(outcome)), 4)
            _update(supa, row, {"status": "settled", "outcome": int(outcome),
                                "settlement_pnl": pnl})
            summary["settled"] += 1
            continue
        if close - CANCEL_BUFFER <= now and oid:
            # Cutoff: kill any unfilled remainder. A partial fill keeps its
            # filled status; the cancel only ends the resting remainder.
            try:
                portfolio.cancel_order(oid)
            except Exception as exc:  # noqa: BLE001 -- expiry also ends it
                summary["errors"].append(f"cancel {row['target']}: {exc}")
            if filled == 0 and row["status"] == "resting":
                _update(supa, row, {"status": "cancelled"})
                summary["cancelled"] += 1
