"""Rest a staged book's protective stops against the positions that actually filled.

Built 2026-11-02 for Kevin's Alpaca mirror book: the entries stage through the machine
API as opening-auction orders, but a stop placed before its entry fills would be a
fresh short waiting at the stop price if the entry failed. This reconciler runs AFTER
the fills: it reads the paper account's positions and resting orders, and places each
spec stop for exactly the uncovered shares held -- sized down to the position, skipped
when the symbol is not held, and skipped when a stop at the same price already rests
(whoever placed it, this script, the machine API, or Kevin in the Alpaca app).

The spec is a JSON list: [{"symbol": "XLE", "qty": 115, "stop_price": 65.55}, ...]
`qty` is the intended coverage; the position is the truth. Stops are plain stop orders,
good-till-cancelled, tagged `ext-<key-id>-stop-mirror-<symbol>-<yyyymmdd>` so the
machine cancel path owns them. Re-running is safe: the plan is a diff, not a script of
orders, and a filled or cancelled stop simply re-enters the plan against the position
that remains.

Usage: python -m tradehub.scripts.mirror_stops --spec stops.json [--key-id 1] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from tradehub.portfolio import paper_orders
from tradehub.portfolio.alpaca_paper import paper_get

PRICE_TOLERANCE = 0.005  # half a cent: the same stop, not a second one a tick away


def plan_stops(desired: list[dict], positions: dict[str, float],
               open_orders: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    """(to_place, [(spec, why_skipped)]) -- the pure diff the runner executes.

    `positions` maps symbol -> signed held qty. `open_orders` are Alpaca-shaped dicts
    (symbol/side/type/stop_price/qty). A desired stop's side comes from the position:
    sell over a long, buy over a short.
    """
    to_place: list[dict] = []
    skipped: list[tuple[dict, str]] = []
    for spec in desired:
        symbol = str(spec["symbol"]).strip().upper()
        held = positions.get(symbol, 0.0)
        if held == 0:
            skipped.append((spec, "no position held"))
            continue
        side = "sell" if held > 0 else "buy"
        want = min(int(spec["qty"]), int(abs(held)))
        resting = sum(int(float(o.get("qty") or 0)) for o in open_orders
                      if (o.get("symbol") or "").upper() == symbol
                      and o.get("side") == side
                      and (o.get("type") or o.get("order_type")) == "stop"
                      and o.get("stop_price") not in (None, "")
                      and abs(float(o["stop_price"]) - float(spec["stop_price"])) < PRICE_TOLERANCE)
        qty = want - resting
        if qty <= 0:
            skipped.append((spec, f"already resting ({resting} of {want} covered)"))
            continue
        to_place.append({"symbol": symbol, "qty": qty, "side": side,
                         "stop_price": float(spec["stop_price"])})
    return to_place, skipped


def _positions() -> dict[str, float]:
    return {(p.get("symbol") or "").upper(): float(p.get("qty") or 0)
            for p in paper_get("/v2/positions") or []}


def _open_orders() -> list[dict]:
    return paper_get("/v2/orders", {"status": "open", "limit": 500}) or []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="JSON list of {symbol, qty, stop_price}")
    parser.add_argument("--key-id", type=int, default=1,
                        help="machine key id whose ext- stop tag family the orders carry")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, place nothing")
    args = parser.parse_args()

    desired = json.loads(Path(args.spec).read_text())
    to_place, skipped = plan_stops(desired, _positions(), _open_orders())
    stamp = date.today().strftime("%Y%m%d")
    for spec, why in skipped:
        print(f"skip  {spec['symbol']:<6} {why}")
    for order in to_place:
        tag = f"ext-{args.key_id}-stop-mirror-{order['symbol'].lower()}-{stamp}"
        line = (f"{'plan ' if args.dry_run else 'place'} {order['symbol']:<6} {order['side']} "
                f"{order['qty']} stop {order['stop_price']:.2f} gtc  ({tag})")
        if args.dry_run:
            print(line)
            continue
        try:
            placed: dict[str, Any] = paper_orders.submit(
                order["symbol"], order["qty"], order["side"], tag,
                order_type="stop", time_in_force="gtc", stop_price=order["stop_price"])
            print(f"{line} -> {placed.get('status', 'accepted')}")
        except paper_orders.DuplicateOrder:
            print(f"{line} -> already placed (duplicate tag)")
        except (paper_orders.OrdersDisabled, paper_orders.OrderRejected, ValueError) as exc:
            print(f"{line} -> REFUSED: {exc}")
    if not to_place and not skipped:
        print("nothing in the spec")


if __name__ == "__main__":
    main()
