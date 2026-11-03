"""Post-open check of the hub's rule orders against what the broker did with them.

A "sent" order is only an intent: on 2026-11-03 three market-at-open orders were sent and only one
filled, while the log kept saying "sent". Once an order has ended, the broker's answer goes in
paper_order_checks (paper_orders is append-only), and one that ended short raises a manual action.
Orders still working are left to the next pass. Protective stops are skipped: the hub cancels those
on purpose.
"""

from __future__ import annotations

from datetime import date, datetime

from tradehub.workshop import store

CHECKS = "paper_order_checks"
ENDED = ("expired", "canceled", "rejected", "done_for_day", "filled")


def _problem(row: dict, order: dict) -> str | None:
    wanted = float(order.get("qty") or row.get("qty") or 0)
    filled = float(order.get("filled_qty") or 0)
    if filled >= wanted:
        return None
    return (f"{row['side']} {wanted:g} {row['symbol']}: broker says {order.get('status')}, filled {filled:g} of "
            f"{wanted:g}. The position is short of the plan until the next run retries it.")


def reconcile(supa, book: str, since: date, now: datetime, read_orders) -> dict[str, int]:
    """Check one book's rule orders from `since` on with no final answer yet. `read_orders()` is that
    book's broker orders over the same days. `missing` counts sent orders the broker doesn't show."""
    rows = (supa.table(store.ORDERS).select("*").eq("book", book).eq("status", "sent").gte("day", str(since))
            .execute().data or [])
    done = {c["client_order_id"] for c in supa.table(CHECKS).select("client_order_id").eq("book", book)
            .execute().data or []}
    rows = [r for r in rows if "-auto-" in (r.get("client_order_id") or "") and r["client_order_id"] not in done]
    if not rows:
        return {"checked": 0, "problems": 0, "missing": 0}
    orders = {o.get("client_order_id"): o for o in read_orders()}
    checked = problems = missing = 0
    for row in rows:
        order = orders.get(row["client_order_id"])
        if order is None:
            missing += 1
            continue
        if order.get("status") not in ENDED:
            continue
        problem = _problem(row, order)
        if problem:  # raised first: if the record write below fails, the next pass retries, and this dedupes
            problems += 1
            store.add_manual_action(supa, book, row.get("idea_id"), "order", row["symbol"], problem)
        supa.table(CHECKS).insert({
            "book": book, "client_order_id": row["client_order_id"], "broker_status": order["status"],
            "filled_qty": float(order.get("filled_qty") or 0),
            "filled_avg_price": float(order["filled_avg_price"]) if order.get("filled_avg_price") else None,
            "checked_at": now.isoformat()}).execute()
        checked += 1
    return {"checked": checked, "problems": problems, "missing": missing}
