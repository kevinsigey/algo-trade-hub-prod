"""Kalshi DEMO auto-trader for the 15-minute natural gas rule.

Kevin's build (approved 2026-11-11, sizing amended 2026-11-12): follow the
live gate's gated natural-gas buys with real
orders on the Kalshi DEMO account only, sized at 1% of the demo balance per
decision, scaling with the balance. Demo fills do not prove the edge; the
shadow record (the decisions table itself) is the measure.

Decided at freeze time (fix 2026-11-12): the record pass writes a window's
`fifteen_rule_decisions` row only after the window has closed, so the
runner could never see a tradable one. Candidates now come from
fifteen_tracking.open_decisions -- the same per-window decision the
record pass later writes, made while the window is open -- and each
order is checked against the tracking row once it lands
(`decision_mismatch`).

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

import time

from tradehub import fifteen_tracking
from tradehub import oil_fifteen_rule as rule
from tradehub.core.kalshi_portfolio import NotDemoHostError
from tradehub.journal.kalshi_linked import ticker_of
from tradehub.markets import quote_cents

SERIES = "KXNATGAS15M"
GAS_SERIES = tuple(s for s in rule.SERIES if s[0] == "natgas_15m")
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
        "placed": 0, "adopted": 0, "skipped_cap": 0, "skipped_no_depth": 0,
        "cancelled": 0, "settled": 0, "decision_mismatch": 0, "errors": [],
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

    tracked = _tracked_decisions(supa)
    summary["decision_mismatch"] = len(decision_mismatches(rows, tracked))
    _reconcile(supa, portfolio, rows, now, summary, tracked)

    # Fresh gated gas buys for windows still open, decided now exactly as
    # the record pass will record them after the close, stamped with the
    # live gate's version only.
    cutoff = now + CANCEL_BUFFER
    decisions = [d for d in fifteen_tracking.open_decisions(supa, now, series_set=GAS_SERIES)
                 if d["series"] == SERIES and d["action"] == "buy"]
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
        if existing is not None and _adopt_if_accepted(supa, portfolio, existing, summary):
            # The earlier pass's order WAS accepted (its response was
            # lost) and is tracked now. Its contracts already count in
            # contracts_today (the row predates this pass); add its
            # at-risk amount to the loss tally, as a fresh placement does.
            loss_used += int(existing["contracts"]) * float(existing["limit_price"])
            continue
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


def _find_by_client_order_id(portfolio, client_order_id: str) -> dict | None:
    """The exchange's own record of an order we may already have placed."""
    get_orders = getattr(portfolio, "get_orders", None)
    if get_orders is None:
        return None
    try:
        orders = get_orders()
    except Exception:  # noqa: BLE001 -- unreadable is not absent; the caller falls through
        return None
    for order in orders or []:
        if order.get("client_order_id") == client_order_id:
            return order
    return None


def _adopt_if_accepted(supa, portfolio, row: dict, summary: dict) -> bool:
    """A `pending` row whose create_order response was lost may name a
    real, resting Kalshi order. Adopt it -- record the order id and mark
    the row resting -- instead of re-placing: Kalshi rejects the duplicate
    client_order_id, and reconcile would then write the row off as
    placement_interrupted while a live order sat untracked."""
    found = _find_by_client_order_id(portfolio, row["client_order_id"])
    if not found or not found.get("order_id"):
        return False
    _update(supa, row, {"kalshi_order_id": found["order_id"], "status": "resting"})
    summary["adopted"] += 1
    return True


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


def _tracked_decisions(supa) -> dict[str, dict]:
    """The record pass's rows for recent gas windows, by target."""
    return {d["target"]: d for d in _select(supa, DECISIONS, {"series": SERIES},
                                            order="close_time", desc=True, limit=1000)}


def decision_mismatches(rows: list[dict], tracked: dict[str, dict]) -> list[str]:
    """Targets where what the runner traded on (a buy of `side` at
    `limit_price`, which is the decision's cost) differs from the record
    pass's row for the same window. No schema change: the order row
    already carries the decision's side and cost."""
    out = []
    for r in rows:
        d = tracked.get(r["target"])
        if d is None:
            continue  # the window has not been recorded yet
        if (d.get("action") != "buy" or d.get("side") != r.get("side")
                or d.get("cost") is None or r.get("limit_price") is None
                or abs(float(d["cost"]) - float(r["limit_price"])) > 1e-9):
            out.append(r["target"])
    return out


def _reconcile(supa, portfolio, rows: list[dict], now: datetime,
               summary: dict, tracked: dict[str, dict]) -> None:
    open_rows = [r for r in rows if r["status"] in OPEN_STATUSES]
    if not open_rows:
        return
    fills = _fills_by_order(portfolio)
    outcomes = {t: d.get("outcome") for t, d in tracked.items()}

    for row in open_rows:
        close = _dt(row["window_close"])
        if row["status"] == "pending":
            if close - CANCEL_BUFFER > now:
                continue
            # Cutoff. The last pass's create may have been accepted with its
            # response lost: adopt the real order by client_order_id and let
            # it fall through to the fill/cancel handling below, rather than
            # writing a live order off as placement_interrupted.
            if not _adopt_if_accepted(supa, portfolio, row, summary):
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


# -- the Portfolio tab report --------------------------------------------------
# Read side for GET /api/kalshi-demo: the live demo account (balance and
# positions, cached ~15s -- the market-data enrichment is one Kalshi read
# per open position) plus this table's own record against the shadow
# record for the same decisions. No new snapshot table: curves and stats
# are computed from kalshi_demo_orders joined to fifteen_rule_decisions.

STARTING_BALANCE_USD = 500.0
NOTE = ("Demo account, fake money, demo order book. Demo fills don't prove "
        "the edge; the shadow record is the measure.")
SUMMARY_TTL_SECONDS = 15.0

_summary_cache: tuple[float, dict] | None = None


def _contracts_of(pos: dict) -> int:
    raw = pos.get("position_fp")
    if raw is None:
        raw = pos.get("position") or 0
    try:
        return int(abs(float(raw)))
    except (TypeError, ValueError):
        return 0


def _avg_price_of(pos: dict, contracts: int, db_row: dict | None) -> float | None:
    """Entry price for a live position: our own order row first (the fill,
    else the limit we placed), the position's remaining cost basis as
    fallback (market_exposure -- what the still-held contracts cost, NOT
    total_traded, which counts every historical trade incl. exits).
    A figure outside (0, 1) is not a price for these contracts -- None."""
    if db_row is not None:
        for key in ("fill_price", "limit_price"):
            value = db_row.get(key)
            if value is not None and 0 < float(value) < 1:
                return float(value)
    if contracts > 0:
        basis = pos.get("market_exposure_dollars")
        if basis is None and pos.get("market_exposure") is not None:
            basis = float(pos["market_exposure"]) / 100.0
        if basis:
            avg = float(basis) / contracts
            if 0 < avg < 1:
                return avg
    return None


def _live_summary(portfolio, rows_by_ticker: dict[str, dict]) -> dict:
    """Balance + enriched open positions from the demo account (one pass;
    the caller caches it). A failed read yields Nones, never a crash."""
    balance = None
    portfolio_value = None
    try:
        data = portfolio.get_balance()
    except Exception:  # noqa: BLE001 -- the tab renders dashes, not a 500
        data = None
    if data:
        if data.get("balance") is not None:
            balance = float(data["balance"]) / 100.0
        if data.get("portfolio_value") is not None:
            portfolio_value = float(data["portfolio_value"]) / 100.0

    positions = []
    positions_unavailable = False
    try:
        # Strict read: a failed request must not read as an empty book.
        raw_positions = portfolio.get_positions_strict()
    except AttributeError:
        raw_positions = portfolio.get_positions() or []
    except Exception:  # noqa: BLE001
        raw_positions = []
        positions_unavailable = True
    for pos in raw_positions:
        contracts = _contracts_of(pos)
        ticker = pos.get("ticker")
        if not ticker or contracts <= 0:
            continue
        signed = float(pos.get("position_fp") or pos.get("position") or 0)
        side = "yes" if signed >= 0 else "no"
        db_row = rows_by_ticker.get(ticker)
        avg_price = _avg_price_of(pos, contracts, db_row)
        market = None
        try:
            got = portfolio.get_market_data(ticker)
            market = (got or {}).get("market") if got else None
        except Exception:  # noqa: BLE001
            market = None
        quotes = quote_cents(market) if market else {}
        bid_cents = quotes.get("yes_bid") if side == "yes" else quotes.get("no_bid")
        open_pnl = None
        if bid_cents is not None and avg_price is not None:
            open_pnl = round((bid_cents / 100.0 - avg_price) * contracts, 2)
        strike = None
        if market and market.get("floor_strike") is not None:
            try:
                strike = float(market["floor_strike"])
            except (TypeError, ValueError):
                strike = None
        positions.append({
            "ticker": ticker,
            "series": ticker.split("-")[0],
            "strike": strike,
            "side": side,
            "contracts": contracts,
            "avg_price": avg_price,
            "yes_bid": None if quotes.get("yes_bid") is None else quotes["yes_bid"] / 100.0,
            "yes_ask": None if quotes.get("yes_ask") is None else quotes["yes_ask"] / 100.0,
            "open_pnl": open_pnl,
            "close_time": (market or {}).get("close_time")
                          or (db_row or {}).get("window_close"),
        })
    return {"balance": balance, "portfolio_value": portfolio_value,
            "positions": positions,
            "positions_unavailable": positions_unavailable}


def live_summary(portfolio, rows_by_ticker: dict[str, dict],
                 clock=time.monotonic) -> dict:
    """The live account read behind a ~15s cache. There is exactly one
    demo account, and the endpoint constructs a fresh client per request,
    so the cache is a single slot; tests clear it between cases."""
    global _summary_cache
    if _summary_cache is not None and clock() - _summary_cache[0] < SUMMARY_TTL_SECONDS:
        return _summary_cache[1]
    summary = _live_summary(portfolio, rows_by_ticker)
    # A failed positions read is never cached: the next request retries
    # instead of serving the false empty book for the rest of the TTL.
    if not summary.get("positions_unavailable"):
        _summary_cache = (clock(), summary)
    return summary


def build_report(supa, portfolio, now: datetime, clock=time.monotonic) -> dict:
    rows = _select(supa, ORDERS, {}, order="created_at", desc=True, limit=500)
    rows_by_ticker = {r["ticker"]: r for r in rows
                      if r["status"] in ("resting", "filled")}
    live = live_summary(portfolio, rows_by_ticker, clock=clock)

    settled = sorted((r for r in rows if r["status"] == "settled"),
                     key=lambda r: str(r["window_close"]))
    decisions = _tracked_decisions(supa) if rows else {}
    demo_curve: list[dict] = []
    shadow_curve: list[dict] = []
    shadow_pc_curve: list[dict] = []
    demo_total = shadow_total = shadow_pc_total = 0.0
    for r in settled:
        at = _iso(_dt(r["window_close"]))
        demo_total += float(r.get("settlement_pnl") or 0)
        demo_curve.append({"at": at, "pnl": round(demo_total, 2)})
        d = decisions.get(r["target"])
        if d is not None and d.get("pnl") is not None:
            filled = int(r.get("contracts_filled") or 0)
            shadow_total += float(d["pnl"]) * filled
            shadow_pc_total += float(d["pnl"])
            shadow_curve.append({"at": at, "pnl": round(shadow_total, 2)})
            shadow_pc_curve.append({"at": at, "pnl": round(shadow_pc_total, 2)})

    placed = [r for r in rows if r.get("kalshi_order_id")]
    filled_orders = [r for r in placed if int(r.get("contracts_filled") or 0) > 0]
    slips = [(float(r["fill_price"]) - float(r["frozen_quote"])) * 100.0
             for r in rows if r.get("fill_price") is not None]
    settled_filled = sum(int(r.get("contracts_filled") or 0) for r in settled)
    wins = sum(1 for r in settled if float(r.get("settlement_pnl") or 0) > 0)
    today_et = now.astimezone(ET).date()
    pnl_today = sum(float(r.get("settlement_pnl") or 0) for r in settled
                    if _dt(r["window_close"]).astimezone(ET).date() == today_et)
    if live["balance"] is not None:
        pnl_since_start = round(live["balance"]
                                + (live["portfolio_value"] or 0.0)
                                - STARTING_BALANCE_USD, 2)
    else:
        pnl_since_start = round(demo_total, 2)

    return {
        "state": "live",
        "demo": True,
        "as_of": _iso(now),
        "balance": live["balance"],
        "starting_balance": STARTING_BALANCE_USD,
        "pnl_since_start": pnl_since_start,
        "pnl_today": round(pnl_today, 2),
        "positions": live["positions"],
        "positions_unavailable": bool(live.get("positions_unavailable")),
        "performance": {
            "demo_curve": demo_curve,
            "shadow_curve": shadow_curve,
            "shadow_curve_per_contract": shadow_pc_curve,
            "fill_rate": (round(len(filled_orders) / len(placed), 4)
                          if placed else None),
            "avg_slippage_cents": (round(sum(slips) / len(slips), 2)
                                   if slips else None),
            "win_rate": round(wins / len(settled), 4) if settled else None,
            "pnl_per_contract": (round(demo_total / settled_filled, 4)
                                 if settled_filled else None),
            # Orders whose decision differs from the record pass's row for
            # the same window -- should be 0: both run the same decision.
            "decision_mismatch": len(decision_mismatches(rows, decisions)),
            "decisions_not_traded": {
                "caps": sum(1 for r in rows if r["status"] == "skipped_cap"),
                "no_depth": sum(1 for r in rows
                                if r["status"] == "skipped_no_depth"),
                "missed": sum(1 for r in rows if r["status"] == "cancelled"
                              and r.get("skip_reason") == "placement_interrupted"),
            },
        },
        "orders": [{
            "id": r["id"], "created_at": r["created_at"],
            "target": r["target"], "ticker": r["ticker"], "side": r["side"],
            "gate_version": r.get("gate_version"),
            "contracts": r["contracts"],
            "contracts_filled": r.get("contracts_filled") or 0,
            "limit_price": r["limit_price"], "frozen_quote": r["frozen_quote"],
            "ask_size": r.get("ask_size"), "status": r["status"],
            "skip_reason": r.get("skip_reason"),
            "fill_price": r.get("fill_price"), "filled_at": r.get("filled_at"),
            "window_close": r["window_close"], "outcome": r.get("outcome"),
            "settlement_pnl": r.get("settlement_pnl"),
        } for r in rows],
        "note": NOTE,
    }
