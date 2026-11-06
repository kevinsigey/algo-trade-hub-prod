"""Cron entrypoint: automated PAPER orders for switched-on ideas (Trading HQ step 4).

Run at 12:30 UTC Mon-Fri by `tradehub-paper-orders.timer` (07:30 or 08:30 New York, before the open). For each idea
whose orders are on: today's target from its confirmed rule (engine.target_today, the backtest's own lag rules),
the orders that close the gap (autotrade.plan), sent through the one paper-only order path. Ideas switched off or
killed get their own shares closed. Every row - sent, already sent, skipped, rejected - is logged in paper_orders.
Nothing is sent unless TRADEHUB_PAPER_ORDERS=on; one idea failing never stops the others.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import requests

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio import book, books, breakers, paper_orders, service
from tradehub.portfolio import options as opt_mod
from tradehub.portfolio.alpaca_paper import AccountNotConnected
from tradehub.portfolio.autotrade import close_options, close_out, plan, plan_options
from tradehub.scripts.ideas_shadow import FRED_LEAD
from tradehub.scripts.paper_orders_protect import _cancel
from tradehub.workshop import data, store
from tradehub.workshop.data import NY
from tradehub.workshop.engine import EXIT_COOLDOWN, daily_frame, target_and_reason, tickers_for
from tradehub.workshop.spec import IdeaSpec


def _send(row: dict, submit) -> dict:
    if row["status"] == "manual":
        return row  # a hand-off for Kevin's hand (recorded as a manual action by the caller)
    if row["status"] != "send":
        return {**row, "status": "skipped"}
    if not paper_orders.orders_enabled():
        return {**row, "status": "skipped", "reason": "TRADEHUB_PAPER_ORDERS is off"}
    try:
        sent = submit(row["symbol"], row["qty"], row["side"], row["client_order_id"], order_type=row["order_type"],
                      time_in_force=row["time_in_force"], limit_price=row["limit_price"],
                      **({"legs": row["mleg"]} if row.get("mleg") else {}))
        return {**row, "status": "sent", "alpaca_order_id": sent.get("id")}
    except paper_orders.DuplicateOrder:
        return {**row, "status": "already sent", "reason": "sent earlier this morning"}
    except (paper_orders.OrderRejected, AccountNotConnected, requests.RequestException) as exc:
        return {**row, "status": "rejected", "reason": str(exc)[:200]}


def _needs_shares(row: dict, held: dict[str, float]) -> dict:
    """A covered call sent before its shares are held is refused as uncovered, and the shares and the
    call are planned in the same pre-market run. Hold it back; the next run sends it, no alarm needed."""
    if not (row.get("option") and row["status"] == "send" and row["side"] == "sell" and row["kind"] == "open"
            and not row.get("mleg")):
        return row
    contract = opt_mod.parse_occ(row["symbol"])
    if contract["kind"] != "call" or held.get(contract["underlying"], 0.0) >= row["qty"] * 100:
        return row
    return {**row, "status": "skip", "waiting": True,
            "reason": f"waiting for the {contract['underlying']} shares to fill; the next run sends this call"}


def _exit_text(spec: IdeaSpec, why: str) -> str:
    """'stop-loss 5% hit' etc., for the exit that keeps the idea flat this morning ('' when the rule did it)."""
    if not why:
        return ""
    e = spec.exits
    if why == "time":
        return f"time stop: {e.max_days} days held"
    pct = {"stop-loss": e.stop_loss_pct, "trailing": e.trailing_pct, "take-profit": e.take_profit_pct}.get(why)
    if pct is None and why not in ("", "time"):
        return ""
    return f"{why.replace('trailing', 'trailing stop')} {pct:g}% hit"

def _stopped_out(idea_id: int, spec: IdeaSpec, fills: list[dict], client_ids: dict[str, str], prices_frame,
                 series) -> str:
    """Why the idea may not reopen yet after one of its real stop orders filled, or '' when it may."""
    if spec.exits.mode != "intraday":
        return ""
    prefix = f"idea-{idea_id}-stop-"
    stops = [f["transaction_time"][:10] for f in fills if client_ids.get(f.get("order_id"), "").startswith(prefix)]
    if not stops:
        return ""
    last = max(stops)
    after = daily_frame(spec, prices_frame, series, data.div_yields(spec, prices_frame))
    after = after[after.index > pd.Timestamp(last)]
    fresh = (not after["on"].all()) if spec.rules is not None else len(after) >= EXIT_COOLDOWN
    return "" if fresh else f"stopped out on {last}; waiting for a fresh signal"


class StalePrices(Exception):
    """The rule's prices don't reach the last trading day yet: the target would be the day before's."""


def _stops_under_moves(pending: list[dict], moves: dict[str, tuple[int, str]]) -> list[dict]:
    """Machine stops already resting when a move was made. A stop placed after the move stays, and so does any
    order whose age can't be read: cancelling is what removes protection."""
    return [o for o in pending
            if paper_orders.MACHINE_STOP_TAG.match(o.get("client_order_id") or "")
            and o["symbol"] in moves and o.get("submitted_at")
            and datetime.fromisoformat(o["submitted_at"]) <= datetime.fromisoformat(moves[o["symbol"]][1])]


def _run(now: datetime, supa, book_name: str, *, submit=paper_orders.submit, closes=data.closes,
         fred=data.fred_series, bars=data.bars, analyst=data.analyst, cancel=paper_orders.cancel,
         cancel_machine=paper_orders.cancel_machine_order) -> tuple[dict, dict[int, str]]:
    day = now.astimezone(NY).date()
    try:
        calendar = [date.fromisoformat(c["date"]) for c in
                    service.paper_get("/v2/calendar", {"start": str(day - timedelta(days=10)), "end": str(day)})]
        if day not in calendar:
            return {"market": "closed"}, {}
        prev_day = max(d for d in calendar if d < day)
        equity = float(service.paper_get("/v2/account")["equity"])
        if equity <= 0:  # every target would be zero and every held share would be sold
            return {"account": "no equity"}, {}
        positions = service.paper_get("/v2/positions")
        pending = service.paper_get("/v2/orders", {"status": "open", "limit": 500, "nested": "true"})
        # Fail closed: unlike the public page, an unreadable order map or label table stops the run. Unknown
        # holdings would look like zero shares and every idea would buy its full size again.
        client_ids = service._orders()
        raw_fills, titles, labels = service._fills(), service._titles(supa, public=False), store.labels(supa)
        fills = book.tag_fills(raw_fills, client_ids, labels, titles)
        named = {order for order, idea_id in labels.items() if idea_id is not None}  # a None label is still manual
        moves = store.manual_moves(supa, book_name)
        moved = book.manual_move_orders(fills, moves, named)
        for order_id, idea_id in moved.items():  # a rebalance: the idea takes the shares, and trades the difference
            store.add_label(supa, order_id, idea_id, "rebalance")
        if moved:
            fills = book.tag_fills(raw_fills, client_ids, {**labels, **moved}, titles)
    except AccountNotConnected:
        return {"account": "not connected"}, {}
    # Shares per symbol per idea id (FIFO lots, tags + relabels); account-wide signed value per symbol.
    lots = book.open_lots([{**f, "idea": f["idea_id"] if f["idea_id"] is not None else book.MANUAL} for f in fills])
    account = {p["symbol"]: float(p["market_value"]) for p in positions}
    last_px = {p["symbol"]: float(p["current_price"]) for p in positions if p.get("current_price")}
    # Orders still waiting to fill (an earlier run this morning, or Kevin's) count toward the 25% limit.
    need = sorted({o["symbol"] for o in pending if not o.get("limit_price")} - set(last_px))
    if need:
        frame = closes(need, day - timedelta(days=14))
        last_px.update({s: float(frame[s].dropna().iloc[-1]) for s in need if s in frame and frame[s].notna().any()})
    waiting = [(o.get("client_order_id") or "", o["symbol"],
                float(o["qty"]) * (1 if o["side"] == "buy" else -1)
                * float(o.get("limit_price") or last_px.get(o["symbol"], 0.0))) for o in pending
               if not paper_orders.STOP_TAG.match(o.get("client_order_id") or "")]  # stops protect, never add

    chain_cache: dict[tuple, list] = {}

    def _select(leg, spot: float):
        key = (leg.underlying, leg.kind)
        if key not in chain_cache:
            target = day + timedelta(days=leg.days_to_expiry)
            chain_cache[key] = opt_mod.fetch_contracts(leg.underlying, leg.kind, target, book=book_name)
        return opt_mod.select_contract(chain_cache[key], leg, spot, day)

    def _mid(occ: str):
        return opt_mod.fetch_mid(occ, book=book_name)

    def _touch(sym: str, side: str):
        return opt_mod.fetch_touch(sym, side, book=book_name)

    breaker = breakers.check(supa, book_name)
    if breaker["tripped"]:
        breakers.notify(supa, book_name, breaker)

    summary: dict = {}
    failed: dict[int, str] = {}
    # Track first order SENT this run per symbol (stock/ETF only): symbol -> (side, idea_id)
    sent_this_run: dict[str, tuple[str, int]] = {}
    if book_name == "main":  # the main book's live state lives on the idea rows (the record)
        jobs = [(i, False) for i in store.auto_ideas(supa)] + [(i, True) for i in store.closing_ideas(supa)]
    else:  # every other book reads its own activations: different ideas, sizes, strategies
        jobs = ([(i, False) for i in store.auto_activations(supa, book_name)]
                + [(i, True) for i in store.closing_activations(supa, book_name)])
    managed = {idea["id"] for idea, _ in jobs}
    uncertain: set[str] = set()  # symbols whose old stop may still rest, or just sold: nothing trades them today
    # Kevin, 2026-11-05: an open sell stop blocks the idea's orders. It goes before any idea plans, because other
    # ideas buy the same symbol. Only a move to an idea with a job: otherwise nothing would manage the shares.
    for order in _stops_under_moves(pending, moves):
        idea_id = moves[order["symbol"]][0]
        if idea_id not in managed:
            continue
        row = _cancel(order, cancel_machine, "a rebalance handed these shares to an idea")
        store.log_orders(supa, idea_id, str(day), [row], book=book_name)
        if row["status"] == "sent":
            pending = [o for o in pending if o["id"] != order["id"]]
            waiting = [w for w in waiting if w[0] != order["client_order_id"]]
            continue
        uncertain.add(order["symbol"])
        if row["status"] != "already sent":
            failed[idea_id] = f"stop on {order['symbol']}: {row['reason']}"[:300]
            store.add_manual_action(supa, book_name, idea_id, "order", order["symbol"], row["reason"] or "needs a hand")
    for idea, closing in jobs:
        try:
            spec = IdeaSpec.model_validate(store.get_run(supa, idea["live_run_id"])["spec"])
            held_all = {s: q[idea["id"]] for s, q in lots.items() if q.get(idea["id"])}
            held = {s: q for s, q in held_all.items() if not opt_mod.is_occ(s)}
            held_contracts = {s: q for s, q in held_all.items() if opt_mod.is_occ(s)}
            mine = f"idea-{idea['id']}-auto-{day:%Y%m%d}-"  # this idea's own orders from earlier this morning
            view = dict(account)
            for cid, symbol, value in waiting:
                if not cid.startswith(mine):
                    view[symbol] = view.get(symbol, 0.0) + value
            if closing:
                rows = close_out(idea["id"], held, last_px, day) if held else []
                if held_contracts:
                    rows += close_options(idea["id"], held_contracts, day, _mid)
            else:
                prices_frame = data.with_rule_bars(spec, closes(tickers_for(spec), spec.start), spec.start,
                                                   bars_fn=bars)
                last = prices_frame.dropna(subset=list(spec.hold) + list(spec.short)).index[-1].date()
                if last < prev_day:
                    raise StalePrices(f"prices end {last}, the last trading day was {prev_day}")
                series = data.rule_series(spec, spec.start - FRED_LEAD, fred=fred, analyst_fn=analyst)
                weights, why = target_and_reason(spec, prices_frame, series,
                                                 data.div_yields(spec, prices_frame))
                if why == "no data":  # no rows to judge: flatten, no exit to name
                    why = ""
                exit_reason = _exit_text(spec, why)
                px = {**last_px, **{s: float(prices_frame[s].dropna().iloc[-1]) for s in weights}}
                rows = plan(idea["id"], weights, float(idea["size_pct"]), equity, px, held, view, day,
                            spec.execution)
                if spec.options:
                    rows += [_needs_shares(r, held) for r in plan_options(
                        idea["id"], list(spec.options), weights, float(idea["size_pct"]),
                        equity, px, held_contracts, day, _select, _mid)]
                waiting_out = _stopped_out(idea["id"], spec, fills, client_ids, prices_frame, series)
                if waiting_out:  # a real stop sold it: no buying back until the rule gives a fresh signal
                    rows = [{**r, "status": "skip", "reason": waiting_out} if r["kind"] == "open" else r
                            for r in rows]
            if breaker["tripped"]:  # closing rows still pass, to get out of positions
                rows = [{**r, "status": "skip", "waiting": True,
                         "reason": f"circuit breaker: {'; '.join(breaker['reasons'])}"}
                        if r["kind"] == "open" and r["status"] in ("send", "manual") else r for r in rows]
            rows = [{**r, "status": "skip", "reason": f"the old stop on {r['symbol']} did not cleanly cancel: waiting a day"}
                    if r["symbol"] in uncertain else r for r in rows]
            if not closing and exit_reason:
                rows = [{**r, "reason": r["reason"] or exit_reason} if r["kind"] == "close" else r for r in rows]
            protecting = [o for o in pending
                          if (o.get("client_order_id") or "").startswith(f"idea-{idea['id']}-stop-")]
            cancels = []
            if protecting and (not held or any(r["status"] == "send" and r["kind"] == "close" for r in rows)):
                # No shares behind a stop means it would OPEN a position if it triggered; a close needs the shares.
                cancels = [_cancel(o, cancel, "closing the position" if held else "no shares to protect")
                           for o in protecting]
            if any(c.get("filled") for c in cancels):  # the stop already sold: selling again would open a short
                rows = [{**r, "status": "skip", "reason": "the protective stop filled first"} if r["kind"] == "close"
                        else r for r in rows]
            # Cross-side check: before sending, skip any "send" row whose symbol already has a sent order
            # on the opposite side from a different idea (stock/ETF only; options ignored).
            for r in rows:
                if r["status"] == "send" and not opt_mod.is_occ(r["symbol"]):
                    existing = sent_this_run.get(r["symbol"])
                    if existing:
                        other_side, other_id = existing
                        if other_side != r["side"] and other_id != idea["id"]:
                            # Opposite side from a different idea: skip with specific reason
                            rows = [
                                {**rr, "status": "skip", "reason": f"crossed with idea {other_id}'s {other_side} of {rr['symbol']} today; retried tomorrow"}
                                if rr is r else rr for rr in rows
                            ]
            # Re-price single-leg option orders at the touch (bid for sell, ask for buy).
            for r in rows:
                if r["status"] == "send" and opt_mod.is_occ(r["symbol"]) and not r.get("mleg"):
                    touch = _touch(r["symbol"], r["side"])
                    if touch is not None:
                        r["limit_price"] = touch
                        r["price"] = touch
            done = cancels + [_send(r, submit) for r in rows]
            # Record sent orders (first one wins per symbol)
            for r in done:
                if r["status"] == "sent" and not opt_mod.is_occ(r["symbol"]) and r["symbol"] not in sent_this_run:
                    sent_this_run[r["symbol"]] = (r["side"], idea["id"])
            for r in done:
                if r["status"] == "manual":
                    store.add_manual_action(supa, book_name, idea["id"], "option", r["symbol"],
                                            r["reason"] or "needs a hand")
                elif r["status"] == "rejected" or (r["status"] == "skipped" and r.get("option") and not r.get("waiting")):
                    # Kevin, 2026-11-03: a rejected order or an unplaceable option leg is
                    # never silent -- it becomes a manual action (deduped while open).
                    # Idea 50's refused short leg and Idea 16's unwritable covered call
                    # both passed without a trace before this rule.
                    store.add_manual_action(supa, book_name, idea["id"],
                                            "option" if (r.get("option") or opt_mod.is_occ(r["symbol"])) else "order",
                                            r["symbol"], r["reason"] or "needs a hand")
            for r in done:
                if r["status"] == "sent" and "price" in r:  # later ideas see this run's orders in the 25% check
                    signed = r["qty"] * (1 if r["side"] == "buy" else -1) * r["price"]
                    account[r["symbol"]] = account.get(r["symbol"], 0.0) + signed
            store.log_orders(supa, idea["id"], str(day), done, book=book_name)
            summary[idea["id"]] = {s: sum(r["status"] == s for r in done) for s in
                                   ("sent", "already sent", "skipped", "rejected")}
            if summary[idea["id"]]["rejected"]:
                failed[idea["id"]] = f"{summary[idea['id']]['rejected']} order(s) rejected"
        except Exception as exc:  # noqa: BLE001 -- logged; the other ideas still trade
            failed[idea["id"]] = f"{type(exc).__name__}: {exc}"[:300]
    return summary, failed


def run(now: datetime, supa, *, book_name: str = "main", submit=None, closes=data.closes,
        fred=data.fred_series, bars=data.bars, analyst=data.analyst, cancel=None, cancel_machine=None
        ) -> tuple[dict, dict[int, str]]:
    """One book's morning pass. The book rides the context variable so every account read
    below (account, positions, orders, fills) resolves to that book's own Alpaca account."""
    if submit is None:
        def submit(symbol, qty, side, client_order_id, **kw):
            if kw.get("legs"):
                return paper_orders.submit_mleg(kw["legs"], qty, kw.get("limit_price"),
                                                client_order_id, book=book_name)
            return paper_orders.submit(symbol, qty, side, client_order_id, book=book_name, **kw)
    cancel = cancel or (lambda *a, **k: paper_orders.cancel(*a, book=book_name, **k))
    cancel_machine = cancel_machine or (lambda *a, **k: paper_orders.cancel_machine_order(*a, book=book_name, **k))
    token = books.use_book(book_name)
    try:
        return _run(now, supa, book_name, submit=submit, closes=closes, fred=fred, bars=bars,
                    analyst=analyst, cancel=cancel, cancel_machine=cancel_machine)
    finally:
        books.reset_book(token)


def exit_code(summary: dict, failed: dict) -> int:
    """1 when anything needs a look: an idea failed or had a rejection, or the account couldn't be used."""
    return 1 if failed or "account" in summary else 0


def main() -> int:
    load_local_env()
    supa = get_client()
    all_summary: dict = {}
    all_failed: dict = {}
    code = 0
    for name in books.names():  # each book trades its own activations against its own account
        try:
            summary, failed = run(datetime.now(UTC), supa, book_name=name)
        except Exception as exc:  # noqa: BLE001 -- one book failing never stops the other
            print(json.dumps({"orders": "failed", "book": name, "error": str(exc)}))
            code = 1
            continue
        all_summary[name] = summary
        if failed:
            all_failed[name] = failed
        code = code or exit_code(summary, failed)
    print(json.dumps({"orders": "failed" if code else "ok", "books": all_summary, "failed": all_failed}))
    return code


if __name__ == "__main__":
    sys.exit(main())
