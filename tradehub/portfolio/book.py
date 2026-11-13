"""Pure book math for the public Portfolio page: Alpaca JSON + stored snapshots in, page numbers out.

Unknown is `None`, never zero: one snapshot has no return yet, and the page shows a dash for it.
Alpaca sends numbers as strings, so everything goes through float().
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict, deque
from datetime import datetime, time
from zoneinfo import ZoneInfo

from tradehub.portfolio.sectors import sector_for

_ET = ZoneInfo("America/New_York")

# A fill belongs to an idea by its order's client_order_id tag (`idea-<id>-...`) or a later relabel (spec §4.6).
MANUAL = "No idea yet (manual)"
TAG = re.compile(r"^idea-(\d+)-")


def tag_id(client_order_id: str | None) -> int | None:
    m = TAG.match(client_order_id or "")
    return int(m.group(1)) if m else None


def tag_fills(fills: list[dict], client_ids: dict[str, str], labels: dict[str, int | None],
              titles: dict[int, str], tags: dict[str, str] | None = None,
              reasons: dict[str, str] | None = None) -> list[dict]:
    """Add `idea_id` and `idea` (title) to each fill. A relabel beats the tag; an id not in `titles` is manual.
    `tags` (order id -> thesis tag) rides along as the fill's `tag`, so a manual play's label reaches its lots.
    `reasons` (order id -> stated reason, 2026-11-11) rides along the same way, so a discretionary
    lot keeps the reason its opening order stated."""
    out = []
    for f in fills:
        order = f.get("order_id")
        wanted = labels[order] if order in labels else tag_id(client_ids.get(order))
        idea_id = wanted if wanted in titles else None
        out.append({**f, "idea_id": idea_id, "idea": titles[idea_id] if idea_id is not None else MANUAL,
                    "tag": (tags or {}).get(order), "reason": (reasons or {}).get(order)})
    return out


def manual_move_orders(fills: list[dict], moves: dict[str, tuple[int, str]], labelled: set[str]) -> dict[str, int]:
    """Order id -> idea id for the manual shares a rebalance hands to an idea, so the idea trades only the
    difference. A move covers shares held when it was made: later manual orders stay manual, an order someone
    already labelled keeps its label, and only orders since the symbol's manual shares were last flat move, so
    closed trades keep their record."""
    open_orders: dict[str, list[str]] = {}
    net: dict[str, float] = {}
    for f in fills:  # oldest first
        symbol, order = f["symbol"], f["order_id"]
        if f.get("idea_id") is not None or symbol not in moves or order in labelled:
            continue
        if datetime.fromisoformat(f["transaction_time"]) > datetime.fromisoformat(moves[symbol][1]):
            continue
        open_orders.setdefault(symbol, []).append(order)
        net[symbol] = net.get(symbol, 0.0) + float(f["qty"]) * (1 if f["side"] == "buy" else -1)
        if abs(net[symbol]) < 1e-9:
            open_orders[symbol] = []
    return {order: moves[symbol][0] for symbol, orders in open_orders.items() for order in orders}


def _pct(new: float, old: float) -> float:
    return (new / old - 1) * 100


def _split(qty: float, lots: dict[str, float]) -> list[tuple[str, float]]:
    """Shares per idea for one position: open lots on the same side, scaled down if they exceed the position."""
    same = {idea: q for idea, q in lots.items() if q and (q > 0) == (qty > 0) and idea != MANUAL}
    covered = sum(same.values())
    scale = qty / covered if abs(covered) > abs(qty) else 1.0
    parts = [(idea, q * scale) for idea, q in same.items()]
    rest = qty - sum(q for _, q in parts)
    return parts + ([(MANUAL, rest)] if abs(rest) > 1e-9 else [])


def _num(row: dict, key: str) -> float | None:
    value = row.get(key)
    return float(value) if value not in (None, "") else None


def positions_view(account: dict, positions: list[dict], open_by_idea: dict[str, dict[str, float]] | None = None,
                   lot_tags: dict[str, dict[str, list[str]]] | None = None) -> list[dict]:
    equity = float(account["equity"])
    rows = []
    for p in positions:
        qty, value, pl = float(p["qty"]), float(p["market_value"]), float(p["unrealized_pl"])
        for idea, part in _split(qty, (open_by_idea or {}).get(p["symbol"], {})) if qty else [(MANUAL, qty)]:
            share = part / qty if qty else 1.0
            rows.append({
                "symbol": p["symbol"],
                "sector": sector_for(p["symbol"]),
                "qty": part,
                "side": p.get("side", "long"),
                "market_value": value * share,
                "pct_of_book": abs(value * share) / equity * 100 if equity else None,
                "unrealized_pl": pl * share,
                "idea": idea,
                "tags": list((lot_tags or {}).get(p["symbol"], {}).get(idea, [])),
                "last_price": _num(p, "current_price"),
                "change_pct": None if _num(p, "change_today") is None else _num(p, "change_today") * 100,
                "avg_price": _num(p, "avg_entry_price"),
                "cost_basis": None if _num(p, "cost_basis") is None else _num(p, "cost_basis") * share,
                "day_pl": None if _num(p, "unrealized_intraday_pl") is None else _num(p, "unrealized_intraday_pl") * share,
            })
    cash = float(account["cash"])
    rows.append({"symbol": "Cash", "sector": sector_for("Cash"), "qty": None, "side": None, "market_value": cash,
                 "pct_of_book": cash / equity * 100 if equity else None, "unrealized_pl": None, "idea": None})
    return rows


def account_view(account: dict, trades: list[dict] | None) -> dict:
    """The account rail: Alpaca's own balances, day P&L against yesterday's close, realized P&L from closed trades."""
    equity, last = _num(account, "equity"), _num(account, "last_equity")
    day = equity - last if equity is not None and last else None
    return {"last_equity": last, "day_pl": day, "day_pl_pct": day / last * 100 if day is not None else None,
            "cash": _num(account, "cash"), "buying_power": _num(account, "buying_power"),
            "long_value": _num(account, "long_market_value"), "short_value": _num(account, "short_market_value"),
            "initial_margin": _num(account, "initial_margin"),
            "maintenance_margin": _num(account, "maintenance_margin"),
            "realized_pl": sum(t["pnl"] for t in trades) if trades is not None else None}


_OCC = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def positions_aggregate(rows: list[dict], equity: float | None) -> list[dict]:
    """The per-symbol fold of the position rows (2026-11-08): `positions` repeats a
    symbol once per idea lot, which a machine reader summing nothing misreads --
    GLD held as two 259-share lots read as ~10% of the book when the aggregated
    truth was 518 shares, 20%. One line per symbol: total signed qty, market value,
    signed % of equity, the cost-basis-weighted blended entry, total unrealized P&L.
    Options keep their OCC symbol (their own line, asset="option"); cash is not a
    position and never appears. Biggest line first, by absolute market value.
    The fold also carries the fields the Portfolio page reads per ticker
    (2026-11-12: sector, side, last price, the underlying's change, summed day
    P&L and cost basis), so the page's positions, movers and composition can
    read this one line per symbol instead of the per-idea lots."""
    groups: dict[str, dict] = {}
    for r in rows:
        symbol = r.get("symbol")
        if not symbol or symbol == "Cash" or r.get("qty") is None:
            continue
        g = groups.setdefault(symbol, {"symbol": symbol,
                                       "asset": "option" if _OCC.match(symbol) else "stock",
                                       "qty": 0.0, "market_value": 0.0, "unrealized_pl": 0.0,
                                       "tags": [],
                                       "sector": None, "last_price": None, "change_pct": None,
                                       "day_pl": 0.0,
                                       "_pl_seen": False, "_cost": 0.0, "_cost_qty": 0.0,
                                       "_cb_seen": False, "_day_seen": False,
                                       "_avg_num": 0.0, "_avg_den": 0.0})
        qty = float(r["qty"])
        g["qty"] += qty
        for tag in r.get("tags") or []:
            if tag not in g["tags"]:
                g["tags"].append(tag)
        g["market_value"] += float(r.get("market_value") or 0)
        # The page's per-ticker fields (2026-11-12): sector, last price and the
        # underlying's own change are the same on every lot of a symbol, so the
        # first lot carrying them speaks for the fold; day P&L and cost basis
        # are lot-scaled and sum back to the position's own totals.
        if g["sector"] is None:
            g["sector"] = r.get("sector")
        if g["last_price"] is None and r.get("last_price") is not None:
            g["last_price"] = float(r["last_price"])
        if g["change_pct"] is None and r.get("change_pct") is not None:
            g["change_pct"] = float(r["change_pct"])
        if r.get("day_pl") is not None:
            g["day_pl"] += float(r["day_pl"])
            g["_day_seen"] = True
        if r.get("unrealized_pl") is not None:
            g["unrealized_pl"] += float(r["unrealized_pl"])
            g["_pl_seen"] = True
        if r.get("cost_basis") is not None:
            g["_cost"] += float(r["cost_basis"])
            g["_cost_qty"] += qty
            g["_cb_seen"] = True
        if r.get("avg_price") is not None and qty:
            g["_avg_num"] += float(r["avg_price"]) * qty
            g["_avg_den"] += qty
    out = []
    for g in groups.values():
        if g["_cost_qty"]:
            avg = g["_cost"] / g["_cost_qty"]
        elif g["_avg_den"]:
            avg = g["_avg_num"] / g["_avg_den"]
        else:
            avg = None
        out.append({"symbol": g["symbol"], "asset": g["asset"], "qty": g["qty"],
                    "market_value": g["market_value"],
                    "pct_of_equity": g["market_value"] / equity * 100 if equity else None,
                    "pct_of_book": abs(g["market_value"]) / equity * 100 if equity else None,
                    "avg_entry": avg, "tags": g["tags"],
                    "sector": g["sector"],
                    "side": "long" if g["qty"] > 0 else "short" if g["qty"] < 0 else None,
                    "last_price": g["last_price"], "change_pct": g["change_pct"],
                    "ah_change_pct": None,
                    "day_pl": g["day_pl"] if g["_day_seen"] else None,
                    "cost_basis": g["_cost"] if g["_cb_seen"] else None,
                    "unrealized_pl": g["unrealized_pl"] if g["_pl_seen"] else None})
    return sorted(out, key=lambda a: -abs(a["market_value"]))


def composition(rows: list[dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for r in rows:
        if r["idea"] is None:  # cash
            continue
        g = groups.setdefault(r["idea"], {"idea": r["idea"], "pct_of_book": 0.0, "unrealized_pl": 0.0})
        g["pct_of_book"] += r["pct_of_book"] or 0.0
        g["unrealized_pl"] += r["unrealized_pl"]
    return list(groups.values())


def _daily_closes(snapshots: list[dict]) -> list[float]:
    last_per_day: dict[str, float] = {}
    for s in snapshots:  # sorted by taken_at, so the last write per day wins
        last_per_day[s["taken_at"][:10]] = s["equity"]
    return list(last_per_day.values())


def _sharpe(snapshots: list[dict]) -> float | None:
    closes = _daily_closes(snapshots)
    if len(closes) < 5:
        return None
    returns = [b / a - 1 for a, b in zip(closes, closes[1:])]
    sd = statistics.stdev(returns)
    return statistics.mean(returns) / sd * math.sqrt(252) if sd else None


def _max_drawdown(snapshots: list[dict]) -> float:
    peak, worst = snapshots[0]["equity"], 0.0
    for s in snapshots:
        peak = max(peak, s["equity"])
        worst = min(worst, _pct(s["equity"], peak))
    return worst


def scoreboard(snapshots: list[dict]) -> dict:
    out = {"start_at": None, "equity": None, "return_pct": None, "spy_return_pct": None,
           "ahead_pts": None, "qqq_return_pct": None, "ahead_qqq_pts": None,
           "max_drawdown_pct": None, "sharpe": None}
    if not snapshots:
        return out
    first, last = snapshots[0], snapshots[-1]
    out["start_at"], out["equity"] = first["taken_at"], last["equity"]
    if len(snapshots) < 2:
        return out
    out["return_pct"] = _pct(last["equity"], first["equity"])
    out["spy_return_pct"] = _pct(last["spy_price"], first["spy_price"])
    out["ahead_pts"] = out["return_pct"] - out["spy_return_pct"]
    if first.get("qqq_price") and last.get("qqq_price"):
        out["qqq_return_pct"] = _pct(last["qqq_price"], first["qqq_price"])
        out["ahead_qqq_pts"] = out["return_pct"] - out["qqq_return_pct"]
    out["max_drawdown_pct"] = _max_drawdown(snapshots)
    out["sharpe"] = _sharpe(snapshots)
    return out


def curve(snapshots: list[dict]) -> list[dict]:
    if not snapshots:
        return []
    e0, s0 = snapshots[0]["equity"], snapshots[0]["spy_price"]
    q0 = snapshots[0].get("qqq_price")
    return [{"t": s["taken_at"], "portfolio_pct": _pct(s["equity"], e0), "spy_pct": _pct(s["spy_price"], s0),
             "qqq_pct": _pct(s["qqq_price"], q0) if q0 and s.get("qqq_price") else None}
            for s in snapshots]


# today_split's qqq_price default: "not passed" (a stale/offline read --
# the stored snapshots are all there is) is not the same as an explicit
# None (a live read that failed). Only the first may fall back to the
# last stored price (CodeRabbit, PR #514).
_QQQ_PRICE_OMITTED = object()


def today_split(snapshots: list[dict], now: datetime, equity: float | None = None,
                spy_price: float | None = None,
                qqq_price: float | None | object = _QQQ_PRICE_OMITTED,
                last_equity: float | None = None, spy_prev_close: float | None = None,
                qqq_prev_close: float | None = None) -> dict:
    """Today, split at the 4:00 PM ET close (Portfolio header, 2026-11-12).

    The regular-session figure is measured against the PRIOR CLOSE: the
    broker's `last_equity` when the caller has it (the snapshot series runs
    09:05-16:05 ET, so yesterday's last snapshot is not quite the close --
    Claude's #506 review), else the prior ET day's last snapshot. The
    after-hours figure is the live equity minus the day's close snapshot
    (the first stored snapshot at or after 16:00 ET; before it exists, the
    whole day is the regular figure). SPY and QQQ ride the same split:
    their prior is the previous daily bar's close when given, else the
    prior snapshot's price.

    When no snapshot exists for today at all (a weekend or holiday), the
    figures describe the last snapshot's day instead: state "closed_day",
    that day's regular figures only, no after-hours segment, and the day
    named in `day_label` so the header can label it ("Fri"), not "Today".
    Unknown is None: a book on its first day has no prior close."""
    out: dict = {"state": "no_prior", "prior_close_at": None, "close_at": None,
                 "regular_pl": None, "regular_pct": None,
                 "after_hours_pl": None, "after_hours_pct": None,
                 "spy_regular_pct": None, "spy_after_hours_pct": None,
                 "qqq_regular_pct": None, "qqq_after_hours_pct": None,
                 "for_date": None, "day_label": None, "is_today": True}
    if not snapshots:
        return out
    today = now.astimezone(_ET).date()
    dated = [(_day(s["taken_at"]).astimezone(_ET), s) for s in snapshots]
    et_now = now.astimezone(_ET)
    # The closed-day reading applies only when today genuinely has no
    # session: a weekend, or a weekday past the first snapshot hour (a
    # holiday). A weekday pre-market is not a closed day (Claude's #514
    # review) -- it falls through and reads as a regular day so far.
    closed_day = et_now.weekday() >= 5 or et_now.time() >= time(10, 5)
    if closed_day and all(et.date() != today for et, _ in dated):
        # Closed day: report the last snapshot's own day, in full.
        for_date = dated[-1][0].date()
        if for_date < today:
            prior = None
            day_snaps: list[dict] = []
            close = None
            for et, s in dated:  # sorted by taken_at: the last prior-day write wins
                if et.date() < for_date:
                    prior = s
                elif et.date() == for_date:
                    day_snaps.append(s)
                    if close is None and et.time() >= time(16, 0):
                        close = s
            out["for_date"] = for_date.isoformat()
            out["day_label"] = for_date.strftime("%a")
            out["is_today"] = False
            if prior is None or not day_snaps:
                return out
            close = close or day_snaps[-1]
            prior_eq = float(prior["equity"])
            close_eq = float(close["equity"])
            out["state"] = "closed_day"
            out["prior_close_at"] = prior["taken_at"]
            out["close_at"] = close["taken_at"]
            out["regular_pl"] = round(close_eq - prior_eq, 2)
            out["regular_pct"] = _pct(close_eq, prior_eq) if prior_eq else None
            if prior.get("spy_price") and close.get("spy_price"):
                out["spy_regular_pct"] = _pct(float(close["spy_price"]), float(prior["spy_price"]))
            if prior.get("qqq_price") and close.get("qqq_price"):
                out["qqq_regular_pct"] = _pct(float(close["qqq_price"]), float(prior["qqq_price"]))
            return out
    prior = close = None
    for et, s in dated:  # sorted by taken_at: the last prior-day write wins
        if et.date() < today:
            prior = s
        elif et.date() == today and close is None and et.time() >= time(16, 0):
            close = s
    if prior is None:
        return out
    out["for_date"] = today.isoformat()
    out["day_label"] = today.strftime("%a")
    last = snapshots[-1]
    current_eq = float(equity) if equity is not None else float(last["equity"])
    current_spy = float(spy_price) if spy_price is not None else last.get("spy_price")
    # An omitted qqq_price falls back to the last stored price; an
    # explicit None stays unknown -- passing the stored close off as the
    # current print printed a 0% "after-hours" QQQ move after the bell.
    current_qqq = last.get("qqq_price") if qqq_price is _QQQ_PRICE_OMITTED else qqq_price
    # The broker's last_equity IS the prior close; the prior snapshot is
    # the fallback for reads that have no account (the stale path).
    prior_eq = float(last_equity) if last_equity else float(prior["equity"])
    out["prior_close_at"] = prior["taken_at"]
    if close is not None:
        close_eq = float(close["equity"])
        out["state"] = "after_hours"
        out["close_at"] = close["taken_at"]
        out["regular_pl"] = round(close_eq - prior_eq, 2)
        out["regular_pct"] = _pct(close_eq, prior_eq) if prior_eq else None
        out["after_hours_pl"] = round(current_eq - close_eq, 2)
        out["after_hours_pct"] = _pct(current_eq, close_eq) if close_eq else None
        if spy_prev_close:
            out["spy_regular_pct"] = _pct(float(close["spy_price"]), float(spy_prev_close)) \
                if close.get("spy_price") else None
        elif prior.get("spy_price") and close.get("spy_price"):
            out["spy_regular_pct"] = _pct(float(close["spy_price"]), float(prior["spy_price"]))
        if current_spy is not None and close.get("spy_price"):
            out["spy_after_hours_pct"] = _pct(float(current_spy), float(close["spy_price"]))
        if qqq_prev_close:
            out["qqq_regular_pct"] = _pct(float(close["qqq_price"]), float(qqq_prev_close)) \
                if close.get("qqq_price") else None
        elif prior.get("qqq_price") and close.get("qqq_price"):
            out["qqq_regular_pct"] = _pct(float(close["qqq_price"]), float(prior["qqq_price"]))
        if current_qqq is not None and close.get("qqq_price"):
            out["qqq_after_hours_pct"] = _pct(float(current_qqq), float(close["qqq_price"]))
    else:
        out["state"] = "regular"
        out["regular_pl"] = round(current_eq - prior_eq, 2)
        out["regular_pct"] = _pct(current_eq, prior_eq) if prior_eq else None
        if spy_prev_close and current_spy is not None:
            out["spy_regular_pct"] = _pct(float(current_spy), float(spy_prev_close))
        elif current_spy is not None and prior.get("spy_price"):
            out["spy_regular_pct"] = _pct(float(current_spy), float(prior["spy_price"]))
        if qqq_prev_close and current_qqq is not None:
            out["qqq_regular_pct"] = _pct(float(current_qqq), float(qqq_prev_close))
        elif current_qqq is not None and prior.get("qqq_price"):
            out["qqq_regular_pct"] = _pct(float(current_qqq), float(prior["qqq_price"]))
    return out


def _day(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fifo(fills: list[dict]) -> tuple[list[dict], dict[str, deque]]:
    """FIFO round trips from Alpaca FILL activities, plus the lots still open. Longs qty > 0, shorts qty < 0.
    FIFO runs per idea first: a sale closes its own idea's lots before anyone else's. A trade carries the idea
    of the lot that opened it."""
    lots: dict[str, deque] = defaultdict(deque)  # symbol -> [signed qty, price, time, idea, tag, reason]
    trades = []
    for f in sorted(fills, key=lambda f: f["transaction_time"]):
        qty = float(f["qty"]) * (1 if f["side"] == "buy" else -1)
        price, at = float(f["price"]), f["transaction_time"]
        book, idea = lots[f["symbol"]], f.get("idea", MANUAL)
        lot_tag = f.get("tag")
        lot_reason = f.get("reason")
        while qty and book and (book[0][0] > 0) != (qty > 0):
            # A closing fill takes its own idea's oldest lot first, then the oldest lot of any idea.
            at_lot = next((i for i, lot in enumerate(book) if lot[3] == idea), 0)
            lot = book[at_lot]
            matched = min(abs(qty), abs(lot[0]))
            signed = math.copysign(matched, lot[0])
            trades.append({
                "symbol": f["symbol"], "sector": sector_for(f["symbol"]),
                "qty": signed, "entry_price": lot[1], "exit_price": price,
                "entered_at": lot[2], "exited_at": at, "pnl": (price - lot[1]) * signed,
                "return_pct": _pct(price, lot[1]) * (1 if signed > 0 else -1),
                "held_days": (_day(at).date() - _day(lot[2]).date()).days, "idea": lot[3],
                "reason": lot[5] if len(lot) > 5 else None,
            })
            lot[0] -= signed
            qty += signed
            if not lot[0]:
                del book[at_lot]
        if qty:
            book.append([qty, price, at, idea, lot_tag, lot_reason])
    return trades, lots


def closed_trades(fills: list[dict]) -> list[dict]:
    return _fifo(fills)[0]


def open_lots(fills: list[dict]) -> dict[str, dict[str, float]]:
    """Open signed quantity per symbol per idea."""
    out: dict[str, dict[str, float]] = {}
    for symbol, book in _fifo(fills)[1].items():
        for qty, _, _, idea, _tag, *_rest in book:
            out.setdefault(symbol, {})
            out[symbol][idea] = out[symbol].get(idea, 0.0) + qty
    return {s: v for s, v in out.items() if v}


def open_lot_tags(fills: list[dict]) -> dict[str, dict[str, list[str]]]:
    """Thesis tags on the lots still open, per symbol per idea (2026-11-08): a tag
    belongs to the order that opened the lot, so it survives exactly as long as
    the lot does -- a partial close shrinks the shares, never the label's truth."""
    out: dict[str, dict[str, list[str]]] = {}
    for symbol, book in _fifo(fills)[1].items():
        for _qty, _price, _at, idea, tag, *_rest in book:
            if tag and tag not in out.setdefault(symbol, {}).setdefault(idea, []):
                out[symbol][idea].append(tag)
    return out


def results_split(trades: list[dict]) -> dict:
    """Closed results split the way the Nov 10 review asked for (2026-11-11):
    "tested ideas" (the trade's lot was attributed to a Workshop idea) against
    "discretionary" (everything else), with the discretionary side broken down
    by the reason its opening order stated. Trades closed before the reason
    rule group under "no reason recorded" -- stated, not hidden."""
    def side(rows: list[dict]) -> dict:
        return {"trades": len(rows), "pnl": round(sum(float(t.get("pnl") or 0) for t in rows), 2),
                "wins": sum(1 for t in rows if float(t.get("pnl") or 0) > 0)}

    tested = [t for t in trades if t.get("idea") and t.get("idea") != MANUAL]
    discretionary = [t for t in trades if not t.get("idea") or t.get("idea") == MANUAL]
    by_reason: dict[str, dict] = {}
    for t in discretionary:
        key = t.get("reason") or "no reason recorded"
        slot = by_reason.setdefault(key, {"reason": key, "trades": 0, "pnl": 0.0})
        slot["trades"] += 1
        slot["pnl"] = round(slot["pnl"] + float(t.get("pnl") or 0), 2)
    return {"tested": side(tested),
            "discretionary": {**side(discretionary),
                              "reasons": sorted(by_reason.values(),
                                                key=lambda r: abs(r["pnl"]), reverse=True)}}


def win_rate(trades: list[dict]) -> float | None:
    if not trades:
        return None
    return sum(1 for t in trades if t["pnl"] > 0) / len(trades) * 100


def open_cost(fills: list[dict]) -> dict[str, dict[str, tuple[float, float]]]:
    """Open signed quantity and average entry price per symbol per idea (the base for protective stops)."""
    out: dict[str, dict] = {}
    for symbol, lots in _fifo(fills)[1].items():
        for qty, price, _, idea, _tag, *_rest in lots:
            q, cost = out.setdefault(symbol, {}).get(idea, (0.0, 0.0))
            out[symbol][idea] = (q + qty, cost + qty * price)
    return {s: {i: (q, c / q) for i, (q, c) in v.items() if q} for s, v in out.items()}
