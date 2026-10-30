"""Cron entrypoint: keep exactly one protective order under each intraday-exit position (Trading HQ step 5 B).

Run at 14:45 UTC Mon-Fri by `tradehub-paper-protect.timer` (09:45 or 10:45 New York), after the opening orders fill. For
each switched-on idea whose exits run during the day: the idea's shares and average entry (FIFO lots, tags +
relabels), the one resting exit Alpaca should hold for them (autotrade.protective), and the hub's own resting
stop orders for that idea. Same shape -> left alone; otherwise the stale ones are cancelled and the right one placed.
Ideas switched off or killed have their stops cancelled (the morning job closes the shares). Every action is
logged in paper_orders. Fails closed on unreadable holdings, like the morning job.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import requests

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio import book, paper_orders, service
from tradehub.portfolio.alpaca_paper import AccountNotConnected
from tradehub.portfolio.autotrade import protective, signature
from tradehub.workshop import store
from tradehub.workshop.data import NY
from tradehub.workshop.spec import IdeaSpec

FAILS = (paper_orders.OrderRejected, AccountNotConnected, requests.RequestException)


def _cancel(order: dict, cancel, why: str) -> dict:
    row = {"symbol": order["symbol"], "side": order["side"], "qty": int(float(order["qty"])),
           "client_order_id": order["client_order_id"], "alpaca_order_id": order["id"]}
    try:
        cancel(order["id"], order["client_order_id"])
        return {**row, "status": "sent", "reason": f"cancelled protective order: {why}"}
    except paper_orders.OrderGone:
        return {**row, "status": "already sent", "reason": "protective order already filled or cancelled"}
    except paper_orders.OrdersDisabled:
        return {**row, "status": "skipped", "reason": "TRADEHUB_PAPER_ORDERS is off"}
    except FAILS as exc:
        return {**row, "status": "rejected", "reason": f"cancel failed: {exc}"[:200]}


def _place(order: dict, submit) -> dict:
    kw = {k: order[k] for k in ("order_type", "time_in_force", "limit_price", "stop_price", "trail_percent",
                                "order_class", "take_profit_price") if order.get(k) is not None}
    row = {k: order[k] for k in ("symbol", "side", "qty", "client_order_id")}
    try:
        sent = submit(order["symbol"], order["qty"], order["side"], order["client_order_id"], **kw)
        return {**row, "status": "sent", "alpaca_order_id": sent.get("id"),
                "reason": f"protective {order.get('order_class') or order['order_type']} placed"}
    except paper_orders.DuplicateOrder:
        return {**row, "status": "already sent", "reason": "placed earlier today"}
    except paper_orders.OrdersDisabled:
        return {**row, "status": "skipped", "reason": "TRADEHUB_PAPER_ORDERS is off"}
    except FAILS as exc:
        return {**row, "status": "rejected", "reason": str(exc)[:200]}


def run(now: datetime, supa, *, submit=paper_orders.submit, cancel=paper_orders.cancel) -> tuple[dict, dict]:
    day = now.astimezone(NY).date()
    try:
        if not service.paper_get("/v2/calendar", {"start": str(day), "end": str(day)}):
            return {"market": "closed"}, {}
        pending = service.paper_get("/v2/orders", {"status": "open", "limit": 500, "nested": "true"})
        fills = book.tag_fills(service._fills(), service._orders(), store.labels(supa),
                               service._titles(supa, public=False))
    except AccountNotConnected:
        return {"account": "not connected"}, {}
    costs = book.open_cost([{**f, "idea": f["idea_id"] if f["idea_id"] is not None else book.MANUAL} for f in fills])

    summary: dict = {}
    failed: dict[int, str] = {}
    jobs = [(i, False) for i in store.auto_ideas(supa)] + [(i, True) for i in store.closing_ideas(supa)]
    for idea, closing in jobs:
        try:
            spec = IdeaSpec.model_validate(store.get_run(supa, idea["live_run_id"])["spec"])
            mine = [o for o in pending if (o.get("client_order_id") or "").startswith(f"idea-{idea['id']}-stop-")]
            if spec.exits.mode != "intraday" and not mine:
                continue
            rows: list[dict] = []
            want = None
            if not closing and spec.exits.mode == "intraday":
                leg = (spec.hold or spec.short)[0]
                held, entry = costs.get(leg, {}).get(idea["id"], (0.0, 0.0))
                want = protective(idea["id"], spec.exits, leg, held, entry, day)
            if want is not None and len(mine) == 1 and signature(mine[0]) == signature(want):
                continue
            rows += [_cancel(o, cancel, "the idea is off" if closing else "position changed") for o in mine]
            if want is not None:
                rows.append(_place(want, submit))
            store.log_orders(supa, idea["id"], str(day), rows)
            summary[idea["id"]] = {s: sum(r["status"] == s for r in rows) for s in
                                   ("sent", "already sent", "skipped", "rejected")}
            if summary[idea["id"]]["rejected"]:
                failed[idea["id"]] = f"{summary[idea['id']]['rejected']} protective action(s) rejected"
        except Exception as exc:  # noqa: BLE001 -- logged; the other ideas still get protected
            failed[idea["id"]] = f"{type(exc).__name__}: {exc}"[:300]
    return summary, failed


def main() -> int:
    load_local_env()
    try:
        summary, failed = run(datetime.now(UTC), get_client())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"protect": "failed", "error": str(exc)}))
        return 1
    code = 1 if failed or "account" in summary else 0
    print(json.dumps({"protect": "failed" if code else "ok", "summary": summary, "failed": failed}))
    return code


if __name__ == "__main__":
    sys.exit(main())
