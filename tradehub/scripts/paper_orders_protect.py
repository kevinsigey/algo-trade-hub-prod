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
import time as clock
from datetime import UTC, datetime, time, timedelta

import requests

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio import book, books, paper_orders, service
from tradehub.portfolio.alpaca_paper import AccountNotConnected
from tradehub.portfolio.autotrade import protective, signature
from tradehub.portfolio.reconcile import reconcile
from tradehub.workshop import store
from tradehub.workshop.data import NY
from tradehub.workshop.spec import IdeaSpec

FAILS = (paper_orders.OrderRejected, AccountNotConnected, requests.RequestException)
_sleep = clock.sleep
DONE = ("canceled", "expired", "rejected")
RECHECK_DAYS = 5


def _cancel(order: dict, cancel, why: str) -> dict:
    row = {"symbol": order["symbol"], "side": order["side"], "qty": int(float(order["qty"])),
           "client_order_id": order["client_order_id"], "alpaca_order_id": order["id"]}
    try:
        cancel(order["id"], order["client_order_id"])
        # Alpaca's DELETE only starts the cancel: the shares stay held until the order reads canceled.
        for _ in range(20):
            status = service.paper_get(f"/v2/orders/{order['id']}")["status"]
            if status in DONE:
                return {**row, "status": "sent", "reason": f"cancelled protective order: {why}"}
            if status == "filled":
                return {**row, "status": "already sent", "filled": True,
                        "reason": "the protective order filled before it could be cancelled"}
            _sleep(0.5)
        return {**row, "status": "rejected", "reason": "cancel did not finish within 10 s"}
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


def _jobs(supa, name: str) -> list:
    """One book's protect jobs, the morning runner's split: the main book's live
    state lives on the idea rows; every other book reads its own activations."""
    if name == "main":
        return ([(i, False) for i in store.auto_ideas(supa)]
                + [(i, True) for i in store.closing_ideas(supa)])
    return ([(i, False) for i in store.auto_activations(supa, name)]
            + [(i, True) for i in store.closing_activations(supa, name)])


def _protect_book(now: datetime, supa, name: str, jobs: list, pending: list, costs: dict,
                  *, submit, cancel) -> tuple[dict, dict]:
    day = now.astimezone(NY).date()
    summary: dict = {}
    failed: dict = {}
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
                want = protective(idea["id"], spec.exits, leg, held, entry, f"{now.astimezone(NY):%Y%m%d%H%M}")
            if want is not None and len(mine) == 1 and signature(mine[0]) == signature(want):
                continue
            busy = [o for o in pending if (o.get("client_order_id") or "").startswith(f"idea-{idea['id']}-auto-")]
            if want is not None and busy:
                continue  # its own rule order is still working: a stop now would be a second exit for the shares
            rows += [_cancel(o, cancel, "the idea is off" if closing else "position changed") for o in mine]
            if want is not None and all(r["status"] == "sent" for r in rows):  # only once the old one is gone
                rows.append(_place(want, submit))
            store.log_orders(supa, idea["id"], str(day), rows, book=name)
            summary[idea["id"]] = {s: sum(r["status"] == s for r in rows) for s in
                                   ("sent", "already sent", "skipped", "rejected")}
            if summary[idea["id"]]["rejected"]:
                failed[idea["id"]] = f"{summary[idea['id']]['rejected']} protective action(s) rejected"
        except Exception as exc:  # noqa: BLE001 -- logged; the other ideas still get protected
            failed[idea["id"]] = f"{type(exc).__name__}: {exc}"[:300]
    return summary, failed


def run(now: datetime, supa, *, submit=paper_orders.submit, cancel=paper_orders.cancel) -> tuple[dict, dict]:
    """Protect every book (handover item 6: this job used to read only the main
    book, so a Book 2 intraday-exit idea would have run without its stop). Each
    book's reads and orders run under its own book context; the main book's
    entries keep the flat shape the report has always used, the other books
    nest under their name. One book's dead account never stops the other's
    protection."""
    day = now.astimezone(NY).date()
    try:
        today = service.paper_get("/v2/calendar", {"start": str(day), "end": str(day)})
        if not today:
            return {"market": "closed"}, {}
        hh, mm = (int(x) for x in str(today[0].get("open") or "09:30").split(":")[:2])
        if now.astimezone(NY) < datetime.combine(day, time(hh, mm), NY) + timedelta(minutes=15):
            return {"market": "not open yet"}, {}  # the opening orders must have filled before a stop goes on
    except AccountNotConnected:
        return {"account": "not connected"}, {}
    summary: dict = {}
    failed: dict = {}
    for name in books.names():
        token = books.use_book(name)
        try:
            pending = service.paper_get("/v2/orders", {"status": "open", "limit": 500, "nested": "true"})
            fills = book.tag_fills(service._fills(), service._orders(), store.labels(supa),
                                   service._titles(supa, public=False))
            costs = book.open_cost([{**f, "idea": f["idea_id"] if f["idea_id"] is not None else book.MANUAL}
                                    for f in fills])
            one_summary, one_failed = _protect_book(now, supa, name, _jobs(supa, name), pending, costs,
                                                    submit=submit, cancel=cancel)
        except AccountNotConnected:
            one_summary, one_failed = {}, {"account": "not connected"}
        finally:
            books.reset_book(token)
        if name == "main":
            summary.update(one_summary)
            failed.update(one_failed)
        else:
            if one_summary:
                summary[name] = one_summary
            if one_failed:
                failed[name] = one_failed
    return summary, failed


def check_fills(now: datetime, supa) -> tuple[dict, dict]:
    """Each book's recent orders against the broker's answer. A day limit order ends after this
    job's morning slot, so the days before today are re-checked too."""
    today = now.astimezone(NY).date()
    since = today - timedelta(days=RECHECK_DAYS)
    out, failed = {}, {}
    for name in books.names():
        token = books.use_book(name)
        try:
            out[name] = reconcile(supa, name, since, now, lambda: service.orders_since(since))
            if out[name]["missing"]:
                failed[name] = f"{out[name]['missing']} sent order(s) the broker doesn't show"
        except Exception as exc:  # noqa: BLE001 -- one book failing never stops the other
            failed[name] = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            books.reset_book(token)
    return out, failed


def main() -> int:
    load_local_env()
    supa = get_client()
    now = datetime.now(UTC)
    fills, fills_failed = check_fills(now, supa)
    try:
        summary, failed = run(now, supa)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"protect": "failed", "error": str(exc), "fills": fills, "fills_failed": fills_failed}))
        return 1
    code = 1 if failed or fills_failed or "account" in summary else 0
    print(json.dumps({"protect": "failed" if code else "ok", "summary": summary, "failed": failed,
                      "fills": fills, "fills_failed": fills_failed}))
    return code


if __name__ == "__main__":
    sys.exit(main())
