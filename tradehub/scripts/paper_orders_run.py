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

import requests

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio import book, paper_orders, service
from tradehub.portfolio.alpaca_paper import AccountNotConnected
from tradehub.portfolio.autotrade import close_out, plan
from tradehub.workshop import data, store
from tradehub.workshop.data import NY
from tradehub.workshop.engine import target_and_reason, tickers_for
from tradehub.workshop.spec import IdeaSpec
from tradehub.scripts.ideas_shadow import FRED_LEAD


def _send(row: dict, submit) -> dict:
    if row["status"] != "send":
        return {**row, "status": "skipped"}
    if not paper_orders.orders_enabled():
        return {**row, "status": "skipped", "reason": "TRADEHUB_PAPER_ORDERS is off"}
    try:
        sent = submit(row["symbol"], row["qty"], row["side"], row["client_order_id"], order_type=row["order_type"],
                      time_in_force=row["time_in_force"], limit_price=row["limit_price"])
        return {**row, "status": "sent", "alpaca_order_id": sent.get("id")}
    except paper_orders.DuplicateOrder:
        return {**row, "status": "already sent", "reason": "sent earlier this morning"}
    except (paper_orders.OrderRejected, AccountNotConnected, requests.RequestException) as exc:
        return {**row, "status": "rejected", "reason": str(exc)[:200]}


def _exit_text(spec: IdeaSpec, why: str) -> str:
    """'stop-loss 5% hit' etc., for the exit that keeps the idea flat this morning ('' when the rule did it)."""
    if not why:
        return ""
    e = spec.exits
    if why == "time":
        return f"time stop: {e.max_days} days held"
    pct = {"stop-loss": e.stop_loss_pct, "trailing": e.trailing_pct, "take-profit": e.take_profit_pct}[why]
    return f"{why.replace('trailing', 'trailing stop')} {pct:g}% hit"


class StalePrices(Exception):
    """The rule's prices don't reach the last trading day yet: the target would be the day before's."""


def run(now: datetime, supa, *, submit=paper_orders.submit, closes=data.closes, fred=data.fred_series
        ) -> tuple[dict, dict[int, str]]:
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
        pending = service.paper_get("/v2/orders", {"status": "open", "limit": 500})
        # Fail closed: unlike the public page, an unreadable order map or label table stops the run. Unknown
        # holdings would look like zero shares and every idea would buy its full size again.
        fills = book.tag_fills(service._fills(), service._orders(), store.labels(supa),
                               service._titles(supa, public=False))
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
                * float(o.get("limit_price") or last_px.get(o["symbol"], 0.0))) for o in pending]

    summary: dict = {}
    failed: dict[int, str] = {}
    jobs = [(i, False) for i in store.auto_ideas(supa)] + [(i, True) for i in store.closing_ideas(supa)]
    for idea, closing in jobs:
        try:
            spec = IdeaSpec.model_validate(store.get_run(supa, idea["live_run_id"])["spec"])
            held = {s: q[idea["id"]] for s, q in lots.items() if q.get(idea["id"])}
            mine = f"idea-{idea['id']}-auto-{day:%Y%m%d}-"  # this idea's own orders from earlier this morning
            view = dict(account)
            for cid, symbol, value in waiting:
                if not cid.startswith(mine):
                    view[symbol] = view.get(symbol, 0.0) + value
            if closing:
                if not held:
                    continue
                rows = close_out(idea["id"], held, last_px, day)
            else:
                prices_frame = closes(tickers_for(spec), spec.start)
                last = prices_frame.dropna(subset=list(spec.hold) + list(spec.short)).index[-1].date()
                if last < prev_day:
                    raise StalePrices(f"prices end {last}, the last trading day was {prev_day}")
                series = ({spec.when.series: fred(spec.when.series, spec.start - FRED_LEAD)}
                          if spec.when and spec.when.source == "fred" else {})
                weights, why = target_and_reason(spec, prices_frame, series)
                exit_reason = _exit_text(spec, why)
                px = {**last_px, **{s: float(prices_frame[s].dropna().iloc[-1]) for s in weights}}
                rows = plan(idea["id"], weights, float(idea["size_pct"]), equity, px, held, view, day,
                            spec.execution)
            if not closing and exit_reason:
                rows = [{**r, "reason": r["reason"] or exit_reason} if r["kind"] == "close" else r for r in rows]
            done = [_send(r, submit) for r in rows]
            for r in done:
                if r["status"] == "sent":  # later ideas see this run's orders in the 25% check
                    signed = r["qty"] * (1 if r["side"] == "buy" else -1) * r["price"]
                    account[r["symbol"]] = account.get(r["symbol"], 0.0) + signed
            store.log_orders(supa, idea["id"], str(day), done)
            summary[idea["id"]] = {s: sum(r["status"] == s for r in done) for s in
                                   ("sent", "already sent", "skipped", "rejected")}
            if summary[idea["id"]]["rejected"]:
                failed[idea["id"]] = f"{summary[idea['id']]['rejected']} order(s) rejected"
        except Exception as exc:  # noqa: BLE001 -- logged; the other ideas still trade
            failed[idea["id"]] = f"{type(exc).__name__}: {exc}"[:300]
    return summary, failed


def exit_code(summary: dict, failed: dict) -> int:
    """1 when anything needs a look: an idea failed or had a rejection, or the account couldn't be used."""
    return 1 if failed or "account" in summary else 0


def main() -> int:
    load_local_env()
    try:
        summary, failed = run(datetime.now(UTC), get_client())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"orders": "failed", "error": str(exc)}))
        return 1
    code = exit_code(summary, failed)
    print(json.dumps({"orders": "failed" if code else "ok", "summary": summary, "failed": failed}))
    return code


if __name__ == "__main__":
    sys.exit(main())
