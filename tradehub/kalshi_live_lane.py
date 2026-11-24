"""Kalshi LIVE micro-pilot lane: the 15-minute oil & gas RAW rule on
Kevin's live Kalshi account, real money (issue #590; preregistration
docs/superpowers/specs/2026-11-23-kalshi-live-pilot-prereg.md).

The pilot answers one question the paper record can't: do the paper
fills actually happen? It trades the ORIGINAL rule (oil_fifteen_rule
.pick -- the gross 10-point bar, no fee-netting gate) on the three
locked series (KXWTI15M, KXBRENT15M, KXNATGAS15M), one contract per
decision while the balance is under $45, holds to settlement, and
records every decision's outcome against its paper twin.

Hard rules, all enforced here or in the client guard:

- Writes go only through KalshiLivePortfolio, whose guard requires
  KALSHI_LIVE_ENABLED=1, KALSHI_LIVE_ENV=live and the production host.
  The demo client and this lane can never reach each other's host.
- Buys only, immediate-or-cancel at the live ask: nothing ever rests,
  nothing is ever sold, there are no early exits.
- Hard ceilings in code: 5 contracts per order, 100 contracts per day,
  $25 notional per day. Env vars (KALSHI_LIVE_MAX_*) may lower them,
  never raise them.
- A $2.00 settled loss in an ET session stops new orders for the
  session; a balance under $5.00 halts the lane until Kevin re-enables
  it; the 50-fill execution gate and the 150-trade edge gate halt it
  too. Halts are never lifted automatically -- the halt state lives in
  kalshi_live_state and only Kevin clears it.
- One row per (series, target, lane) in kalshi_live_orders; the unique
  constraint is the never-order-twice guarantee.
- The paper rule, its scoring, the demo lane and the Alpaca books are
  untouched: this module only reads them.
"""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from tradehub import fifteen_tracking, kalshi_prod_book
from tradehub import oil_fifteen_rule as rule
from tradehub.core.kalshi_live_portfolio import NotLiveHostError
from tradehub.fifteen_volregime import clustered_low95
from tradehub.journal import store
from tradehub.journal.kalshi_linked import ticker_of
from tradehub.markets import quote_cents

LANE = "live-raw-v1"
ORDERS = "kalshi_live_orders"
STATE_TABLE = "kalshi_live_state"
DECISIONS = rule.DECISIONS_TABLE
PROD_FILLS = "kalshi_prod_paper_fills"
ALERTS_TABLE = "watcher_alerts"
ALERT_KIND = "kalshi_live"

PASS_INTERVAL = timedelta(minutes=5)     # the runner's cron cadence
CANCEL_BUFFER = timedelta(seconds=60)    # a decision dies a minute before close
FRESHNESS = timedelta(minutes=20)        # a decision older than this is stale
ET = ZoneInfo("America/New_York")

# The pilot's fixed terms (preregistration, issue #590).
STAGE3_BALANCE = 45.0        # stage-3 sizing starts at this balance
STAGE3_PCT = 0.02            # ...at 2% of balance per decision
WINDOW_CAP_CONTRACTS = 3     # under $45: contracts open in one window
WINDOW_CAP_PCT = 0.05        # at $45+: window cost cap, share of balance
DAILY_STOP_USD = 2.00        # settled session loss that stops new orders
FLOOR_USD = 5.00             # balance below this halts the lane
GATE1_FILLS = 50             # execution check at this many live fills
GATE1_MAX_SLIPPAGE = 0.02    # ...halts if mean fill - frozen exceeds 2c
GATE2_TRADES = 150           # edge check at this many settled live trades

# Hard ceilings in code. Env may lower, never raise.
CEILING_PER_ORDER = 5
CEILING_PER_DAY_CONTRACTS = 100
CEILING_PER_DAY_NOTIONAL_USD = 25.0
CEILING_SLIPPAGE = 0.03

SENT_STATUSES = ("placed", "filled", "unfilled", "settled")


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: datetime) -> str:
    return value.isoformat()


# -- money ------------------------------------------------------------------

def taker_fee_usd(contracts: int, price: float) -> float:
    """Kalshi's taker fee for one order, rounded UP to the cent per
    order on the actual count: ceil(0.07 * C * P * (1 - P)). At one
    contract and a 40c price that is ceil(1.68c) = 2c (issue #590)."""
    if contracts <= 0 or price <= 0:
        return 0.0
    raw_cents = 0.07 * contracts * price * (1.0 - price) * 100.0
    return math.ceil(raw_cents - 1e-9) / 100.0


def size_contracts(balance_usd: float, ask: float, stage3_unlocked: bool) -> int:
    """The pilot's sizing table (preregistration): 1 contract under a
    $45 balance, and 1 contract at any balance until the 150-trade gate
    has passed; only then max(1, floor(2% of balance / ask))."""
    if balance_usd < STAGE3_BALANCE or not stage3_unlocked:
        return 1
    if ask <= 0:
        return 1
    return max(1, math.floor(STAGE3_PCT * balance_usd / ask))


def _env_ceiling(name: str, ceiling: float) -> float:
    """An env override may only lower a hard ceiling."""
    raw = os.getenv(name)
    if raw is None:
        return ceiling
    try:
        value = float(raw)
    except ValueError:
        return ceiling
    return min(ceiling, value) if value > 0 else ceiling


def max_per_order() -> int:
    return int(_env_ceiling("KALSHI_LIVE_MAX_CONTRACTS_PER_ORDER",
                            CEILING_PER_ORDER))


def max_contracts_per_day() -> int:
    return int(_env_ceiling("KALSHI_LIVE_MAX_CONTRACTS_PER_DAY",
                            CEILING_PER_DAY_CONTRACTS))


def max_notional_per_day_usd() -> float:
    return _env_ceiling("KALSHI_LIVE_MAX_NOTIONAL_PER_DAY_USD",
                        CEILING_PER_DAY_NOTIONAL_USD)


def max_slippage() -> float:
    """The most the live ask may sit above the frozen quote before the
    cross is refused (the pilot's fixed 3c term)."""
    return _env_ceiling("KALSHI_LIVE_MAX_SLIPPAGE", CEILING_SLIPPAGE)


# -- reads / writes -----------------------------------------------------------

def _select(supa, table: str, filters: dict, order: str | None = None,
            desc: bool = False, limit: int = 1000) -> list[dict]:
    query = supa.table(table).select("*")
    for col, val in filters.items():
        query = query.eq(col, val)
    if order:
        query = query.order(order, desc=desc)
    return query.limit(limit).execute().data or []


def _update(supa, row: dict, patch: dict) -> None:
    (supa.table(ORDERS).update(patch).eq("id", row["id"]).execute())


def _balance_usd(portfolio) -> float | None:
    try:
        got = portfolio.get_balance()
    except Exception:  # noqa: BLE001 -- a dead read is a skip, not a crash
        return None
    if not got or got.get("balance") is None:
        return None
    return float(got["balance"]) / 100.0


# -- lane state (halts and gates persist; they are never auto-lifted) ---------

def _get_state(supa) -> dict[str, Any]:
    """Raises on a failed read: an unread halt must never read as 'not
    halted'. Callers decide (run_once places nothing)."""
    rows = _select(supa, STATE_TABLE, {})
    return {r["key"]: (r.get("value") or {}) for r in rows}


def _set_state(supa, state: dict, key: str, value: dict) -> None:
    state[key] = value
    try:
        patch = {"value": value,
                 "updated_at": _iso(datetime.now(timezone.utc))}
        if _select(supa, STATE_TABLE, {"key": key}, limit=1):
            (supa.table(STATE_TABLE).update(patch)
             .eq("key", key).execute())
        else:
            supa.table(STATE_TABLE).insert({"key": key, **patch}).execute()
    except Exception:  # noqa: BLE001 -- the in-memory copy still guards this pass
        pass


def _halt(supa, state: dict, reason: str, now: datetime) -> None:
    _set_state(supa, state, "halt", {"halted": True, "reason": reason,
                                     "at": _iso(now)})


# -- alerts -------------------------------------------------------------------

def _alert(supa, *, target: str, event: str, title: str, body: str,
           evidence: dict[str, Any] | None = None) -> bool:
    """One pending watcher_alerts row (kind kalshi_live), deduplicated
    on (target, event) across all rows ever written -- the demo lane's
    outbox pattern: an event is announced once, however many passes
    observe it. Fail-soft: a missed alert never breaks the pass."""
    try:
        rows = (supa.table(ALERTS_TABLE).select("id,evidence")
                .eq("kind", ALERT_KIND).execute().data) or []
        for r in rows:
            ev = r.get("evidence") or {}
            if ev.get("target") == target and ev.get("event") == event:
                return False
        ev = dict(evidence or {})
        ev.update({"target": target, "event": event, "lane": LANE})
        supa.table(ALERTS_TABLE).insert({
            "kind": ALERT_KIND, "watch_id": None, "family": "kalshi_live",
            "title": title, "body": body, "evidence": ev,
            "status": "pending",
        }).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


# -- the raw decisions ---------------------------------------------------------

def raw_open_decisions(supa, now: datetime) -> list[dict]:
    """The RAW rule's buys for windows still open, from the same
    first-frozen reads the paper record uses: rule.pick (the gross
    10-point bar) at the frozen quotes, the halt excluded. Read-only.
    A window with no frozen read yet is not a decision and is omitted."""
    out: list[dict] = []
    lo, hi = now + CANCEL_BUFFER, now + timedelta(minutes=15)
    for name, version, _label in rule.SERIES:
        series = fifteen_tracking._BY_NAME[name]["series"]
        targets = [t for t in fifteen_tracking.fetch_targets(supa, name, lo, hi)
                   if _dt(t["cutoff_at"]) > lo]
        if not targets:
            continue
        first = fifteen_tracking._first_forecasts(
            supa, name, version, [t["target"] for t in targets])
        for t in targets:
            frozen = first.get(t["target"])
            if frozen is None:
                continue
            if rule.in_halt(frozen["frozen_at"]):
                continue
            pay = frozen.get("payload") or {}
            choice = rule.pick(float(frozen["probability"]),
                               yes_ask=pay.get("yes_ask"),
                               yes_bid=pay.get("yes_bid"))
            if choice is None:
                continue
            side, cost = choice
            out.append({
                "series": series, "target": t["target"],
                "ticker": ticker_of(t["target"]),
                "side": side, "cost": cost,
                "model_prob": round(float(frozen["probability"]), 5),
                "frozen_at": frozen["frozen_at"],
                "close_time": _iso(_dt(t["cutoff_at"])),
            })
    return out


def _live_cross_raw(portfolio, ticker: str, side: str,
                    model_prob: Any) -> tuple[float, float] | None:
    """(live ask, gross edge there) for the chosen side, from the live
    book -- the demo cross with the RAW bar: the edge is the model's
    chance minus the side's price, no fee netting. None when the book
    or the probability cannot be read."""
    if model_prob is None:
        return None
    try:
        got = portfolio.get_market_data(ticker)
    except Exception:  # noqa: BLE001 -- an unread book is a skip, not a crash
        return None
    market = (got or {}).get("market") if got else None
    if not market:
        return None
    quotes = quote_cents(market)

    def dollars(key: str) -> float | None:
        cents = quotes.get(key)
        return None if cents is None else cents / 100.0

    yes_ask, yes_bid = dollars("yes_ask"), dollars("yes_bid")
    if yes_ask is None or yes_bid is None or not 0.02 < yes_bid <= yes_ask < 0.98:
        return None
    p = float(model_prob)
    if side == "yes":
        return yes_ask, p - yes_ask
    no_ask = dollars("no_ask")
    if no_ask is None:
        return None
    return no_ask, yes_bid - p


class _ProdBook:
    """The cross surface over one production market read (the demo
    lane's adapter, same shape): get_market_data is a pure function of
    the frozen read, and the reader behind it can only GET."""

    def __init__(self, market: dict):
        self._market = market

    def get_market_data(self, ticker: str) -> dict:
        return {"market": self._market}


def _observe_prod_live(supa, d: dict, base_row: dict, contracts: int,
                       prod_keys: set, summary: dict) -> None:
    """The would-have-filled record for one live-lane decision, on all
    three series (issue #590, build item 4): what the production book
    would have done with the same decision under the live lane's own
    raw cross, recorded into kalshi_prod_paper_fills under the lane's
    stamp so the paired comparison exists on every series. Observation
    only; fail-soft, exactly like the demo lane's observer."""
    key = (d["series"], d["target"], LANE)
    if prod_keys is None or key in prod_keys:
        return
    try:
        market = kalshi_prod_book.read_market(base_row["ticker"])
        if market is None:
            return
        quotes = quote_cents(market)
        if all(v is None for v in quotes.values()):
            return

        def dollars(field: str) -> float | None:
            cents = quotes.get(field)
            return None if cents is None else cents / 100.0

        row: dict[str, Any] = {
            "series": d["series"], "target": d["target"],
            "gate_version": LANE, "ticker": base_row["ticker"],
            "side": d["side"], "model_prob": d.get("model_prob"),
            "frozen_quote": base_row.get("frozen_quote"),
            "prod_yes_bid": dollars("yes_bid"),
            "prod_yes_ask": dollars("yes_ask"),
            "prod_no_bid": dollars("no_bid"),
            "prod_no_ask": dollars("no_ask"),
            "ask_size": None, "would_price": None, "contracts": None,
            "status": "no_cross",
            "window_close": base_row["window_close"],
        }
        cross = _live_cross_raw(_ProdBook(market), base_row["ticker"],
                                d["side"], d.get("model_prob"))
        if cross is not None:
            price, edge = cross
            row["would_price"] = price
            row["contracts"] = contracts
            frozen = base_row.get("frozen_quote")
            if edge < rule.MIN_EDGE - 1e-9:
                row["status"] = "no_edge_at_ask"
            elif frozen is not None and price - float(frozen) > max_slippage():
                row["status"] = "slippage_cap"
            else:
                size = kalshi_prod_book.read_ask_size(
                    base_row["ticker"], d["side"], price)
                if size is None:
                    return  # unmeasured depth is not an observation
                row["ask_size"] = size
                row["status"] = "thin" if size < contracts else "would_fill"
        supa.table(PROD_FILLS).insert(row).execute()
        prod_keys.add(key)
        summary["prod_recorded"] += 1
    except Exception as exc:  # noqa: BLE001 -- observation never breaks the pass
        summary["errors"].append(f"prod observe {base_row['target']}: {exc}")


# -- reconcile / settle ---------------------------------------------------------

def _fill_price_of(fill: dict, side: str) -> float | None:
    """A fill's price for the bought side, dollars. Current API fills
    carry fixed-point dollar strings per side; older shapes carried
    cents. Either reads; anything else is unmeasured."""
    for key in (f"{side}_price_dollars",):
        raw = fill.get(key)
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
    raw = fill.get(f"{side}_price")
    if raw is not None:
        try:
            return float(raw) / 100.0
        except (TypeError, ValueError):
            pass
    return None


def _fills_by_order(portfolio) -> dict[str, dict] | None:
    """order_id -> {filled, price} aggregated over the fills read.
    None when the read failed: reconciliation must not treat an unread
    book as unfilled."""
    try:
        fills = portfolio.get_fills(limit=200)
    except Exception:  # noqa: BLE001
        return None
    out: dict[str, dict] = {}
    for f in fills or []:
        oid = f.get("order_id")
        if not oid:
            continue
        try:
            count = int(float(f.get("count") or f.get("count_fp") or 0))
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        agg = out.setdefault(oid, {"filled": 0, "cost": 0.0, "priced": 0})
        agg["filled"] += count
        price = _fill_price_of(f, "yes")  # fills price the YES leg
        if price is not None:
            agg["cost"] += price * count
            agg["priced"] += count
    for agg in out.values():
        agg["price"] = (agg["cost"] / agg["priced"]
                        if agg["priced"] else None)
    return out


def _side_price(fill_agg_price: float | None, side: str) -> float | None:
    """The bought side's price from the YES-leg price."""
    if fill_agg_price is None:
        return None
    return fill_agg_price if side == "yes" else round(1.0 - fill_agg_price, 4)


def _executed(order: dict, side: str, filled: int,
              limit: float) -> tuple[float, float, str | None]:
    """(fill price, fee usd, flag) from the create response: V2's
    average_fill_price (YES-leg dollars) and average_fee_paid (per
    contract), else the legacy taker_fill_cost / taker_fees (cents,
    order totals). A price outside (0, limit] or a missing field falls
    back to the limit / the computed fee, flagged -- the limit is the
    worst an IOC buy can fill at."""
    flags = []
    try:
        if order.get("average_fill_price") is not None:
            price = _side_price(float(order["average_fill_price"]), side)
        else:
            price = float(order["taker_fill_cost"]) / 100.0 / filled
    except (TypeError, ValueError, KeyError):
        price = None
    if price is None or not 0 < price <= limit + 1e-9:
        price = limit
        flags.append("fill_price_from_limit")
    try:
        if order.get("average_fee_paid") is not None:
            fee = round(float(order["average_fee_paid"]) * filled, 4)
        else:
            fee = float(order["taker_fees"]) / 100.0
    except (TypeError, ValueError, KeyError):
        fee = None
    if fee is None or not 0 <= fee <= filled * price:  # unit slip = bogus
        fee = taker_fee_usd(filled, price)
        flags.append("fee_estimated")
    return price, fee, ",".join(flags) or None


def _reconcile(supa, portfolio, rows: list[dict], now: datetime,
               summary: dict) -> None:
    """Close out placed rows: adopt fill counts from the exchange's
    fills, settle rows whose window outcome has landed (live P&L net
    of the actual fee; the paper twin's P&L from the raw rule at the
    frozen quote, one contract), link the tracked decision row, and
    write off claims the exchange never took."""
    open_rows = [r for r in rows
                 if r["status"] in ("pending", "placed", "filled")]
    if not open_rows:
        return
    # Adoption: a claim whose create response was lost has no order id;
    # sweep the exchange's orders by client_order_id (resting, executed
    # and canceled views) and adopt what it holds before judging it.
    missing = [r for r in open_rows if not r.get("kalshi_order_id")]
    if missing:
        try:
            exchange = []
            for status in (None, "executed", "canceled"):
                exchange.extend(portfolio.get_orders(status=status) or [])
            by_client = {o.get("client_order_id"): o for o in exchange
                         if o.get("client_order_id")}
        except Exception as exc:  # noqa: BLE001 -- adoption retries next pass
            by_client = None
            summary["errors"].append(f"orders read: {exc}")
        for r in missing if by_client is not None else []:
            found = by_client.get(r.get("client_order_id"))
            if found and found.get("order_id"):
                _update(supa, r, {"kalshi_order_id": found["order_id"]})
                r["kalshi_order_id"] = found["order_id"]
    # An unread order book never proves a claim was never placed.
    missing_read_ok = not missing or by_client is not None
    fills = _fills_by_order(portfolio)
    settled_map = store.fetch_settlements(
        supa, [r["target"] for r in open_rows])
    for r in open_rows:
        patch: dict[str, Any] = {}
        closed = _dt(r["window_close"]) <= now
        if r["status"] == "pending" and closed and missing_read_ok:
            # A claim whose placement never landed and whose window has
            # closed: the exchange holds nothing under this key.
            if r.get("kalshi_order_id") is None:
                _update(supa, r, {"status": "failed",
                                  "skip_reason": "placement_interrupted"})
                r["status"] = "failed"
                summary["failed"] += 1
                _alert(supa, target=r["target"], event="placement_interrupted",
                       title=f"Kalshi live claim never placed: {r['ticker']}",
                       body=("The live lane claimed this decision but no "
                             "order reached the exchange before the window "
                             "closed, and no error was recorded. Nothing "
                             "was placed. Real money account."),
                       evidence={"ticker": r["ticker"], "side": r["side"]})
                continue
        if fills is not None and r.get("kalshi_order_id"):
            agg = fills.get(r["kalshi_order_id"])
            if agg and agg["filled"] != int(r.get("contracts_filled") or 0):
                patch["contracts_filled"] = agg["filled"]
                price = _side_price(agg["price"], r["side"])
                if price is not None:
                    patch["fill_price"] = price
                    patch["fee_usd"] = taker_fee_usd(agg["filled"], price)
                r.update(patch)
        filled = int(r.get("contracts_filled") or 0)
        if closed and filled > 0 and r["status"] != "settled":
            outcome = settled_map.get(r["target"])
            if outcome is None:
                if patch:
                    _update(supa, r, patch)
                continue
            price = float(r.get("fill_price") or r.get("live_ask")
                          or r["frozen_quote"])
            fee = float(r.get("fee_usd")
                        if r.get("fee_usd") is not None
                        else taker_fee_usd(filled, price))
            won = int(outcome) == 1 if r["side"] == "yes" else int(outcome) == 0
            pnl = round(filled * ((1.0 if won else 0.0) - price) - fee, 4)
            patch.update({
                "status": "settled", "outcome": int(outcome), "pnl": pnl,
                "fee_usd": fee,
                "paper_pnl": rule.pnl(r["side"], float(r["frozen_quote"]),
                                      int(outcome)),
                "settled_at": _iso(now),
            })
            if r.get("decision_id") is None:
                found = _select(supa, DECISIONS,
                                {"series": r["series"], "target": r["target"]},
                                limit=1)
                if found:
                    patch["decision_id"] = found[0]["id"]
            _update(supa, r, patch)
            r.update(patch)
            summary["settled"] += 1
        elif patch:
            _update(supa, r, patch)
            r.update(patch)


# -- the gates ------------------------------------------------------------------

def _per_contract_items(rows: list[dict]) -> list[tuple[tuple[str, str], float]]:
    """One (cluster, pnl-cents) item per filled contract of every
    settled row, clusters keyed by series + ET settlement day -- the
    house day-clustered estimator's input shape."""
    items: list[tuple[tuple[str, str], float]] = []
    for r in rows:
        filled = int(r.get("contracts_filled") or 0)
        if filled <= 0 or r.get("pnl") is None:
            continue
        day = _dt(r["window_close"]).astimezone(ET).date().isoformat()
        per = float(r["pnl"]) / filled * 100.0
        items.extend([((r["series"], day), per)] * filled)
    return items


def _evaluate_gates(supa, state: dict, rows: list[dict], now: datetime,
                    summary: dict) -> None:
    """The pilot's two automatic gates, evaluated each pass once their
    counts land. A tripped gate halts the lane; halts persist in the
    lane state and are never lifted automatically."""
    filled_rows = [r for r in rows if int(r.get("contracts_filled") or 0) > 0]
    sent = [r for r in rows if r["status"] in SENT_STATUSES]
    if "gate1" not in state and len(filled_rows) >= GATE1_FILLS:
        slips = [(float(r.get("fill_price") or r.get("live_ask")
                        or r["frozen_quote"])
                  - float(r["frozen_quote"])) * 100.0
                 for r in filled_rows]
        mean_slip = sum(slips) / len(slips)
        fill_rate = len(filled_rows) / len(sent) if sent else None
        tripped = mean_slip > GATE1_MAX_SLIPPAGE * 100.0
        _set_state(supa, state, "gate1", {
            "result": "halt" if tripped else "pass",
            "mean_slippage_cents": round(mean_slip, 2),
            "fill_rate": None if fill_rate is None else round(fill_rate, 4),
            "fills": len(filled_rows), "at": _iso(now)})
        if tripped:
            _halt(supa, state, "execution_gate", now)
        _alert(supa, target="gate1", event="gate1_halt" if tripped else "gate1_pass",
               title=("Kalshi live pilot HALTED: execution gate"
                      if tripped else "Kalshi live pilot: execution gate passed"),
               body=(f"At {len(filled_rows)} live fills the mean fill price "
                     f"minus the frozen paper price is {mean_slip:+.2f}c "
                     f"(bar: +2.00c); fill rate "
                     f"{'n/a' if fill_rate is None else f'{fill_rate:.0%}'} "
                     f"over {len(sent)} orders sent. "
                     + ("The live lane is halted and stays halted until "
                        "Kevin re-enables it. Real money account."
                        if tripped else
                        "The pilot continues. Real money account.")),
               evidence={"mean_slippage_cents": round(mean_slip, 2),
                         "fill_rate": fill_rate, "fills": len(filled_rows)})
        summary["gate1"] = "halt" if tripped else "pass"

    settled = [r for r in rows if r["status"] == "settled"]
    if "gate2" not in state and len(settled) >= GATE2_TRADES:
        low = clustered_low95(_per_contract_items(settled))
        tripped = low is not None and low < 0
        _set_state(supa, state, "gate2", {
            "result": "halt" if tripped else "pass",
            "low95_cents": None if low is None else round(low, 2),
            "settled": len(settled), "at": _iso(now)})
        if tripped:
            _halt(supa, state, "edge_gate", now)
        else:
            _set_state(supa, state, "stage3", {"unlocked": True,
                                               "at": _iso(now)})
        _alert(supa, target="gate2", event="gate2_halt" if tripped else "gate2_pass",
               title=("Kalshi live pilot HALTED: edge gate"
                      if tripped else "Kalshi live pilot: edge gate passed"),
               body=(f"At {len(settled)} settled live trades the live net "
                     f"per contract (fee-netted, day-clustered) has low95 "
                     f"{'unmeasured' if low is None else f'{low:+.2f}c'} "
                     f"(bar: 0c). "
                     + ("The live lane is halted and stays halted until "
                        "Kevin re-enables it. Real money account."
                        if tripped else
                        "Stage-3 sizing is unlocked at a $45 balance. "
                        "Real money account.")),
               evidence={"low95_cents": low, "settled": len(settled)})
        summary["gate2"] = "halt" if tripped else "pass"


# -- the pass -------------------------------------------------------------------

def run_once(supa, portfolio, now: datetime) -> dict[str, Any]:
    """One live-lane pass: reconcile, evaluate the gates, then trade
    fresh raw buys. `portfolio` is a KalshiLivePortfolio (or a test
    fake with the same surface)."""
    summary: dict[str, Any] = {
        "candidates": 0, "placed": 0, "filled": 0, "unfilled": 0,
        "skipped_cap": 0, "skipped_no_depth": 0, "failed": 0,
        "settled": 0, "prod_recorded": 0, "prod_settled": 0, "errors": [],
    }
    try:
        portfolio.assert_live_host()
    except NotLiveHostError as exc:
        summary["refused"] = str(exc)
        return summary

    started = time.monotonic()
    try:
        state = _get_state(supa)
    except Exception as exc:  # noqa: BLE001 -- unread halt = halt this pass
        session = now.astimezone(ET).date().isoformat()
        summary["halted"] = "state_unreadable"
        summary["errors"].append(f"state read: {exc}")
        _alert(supa, target=f"state-read:{session}", event="state_unreadable",
               title="Kalshi live pilot paused: lane state unreadable",
               body=("The live lane could not read kalshi_live_state, so a "
                     "persisted halt or gate cannot be ruled out. Nothing "
                     "is placed while the read fails. Real money account."),
               evidence={"error": str(exc)[:300]})
        return summary
    rows = _select(supa, ORDERS, {}, order="created_at", desc=True, limit=1000)
    _reconcile(supa, portfolio, rows, now, summary)
    _evaluate_gates(supa, state, rows, now, summary)

    # The production-book settle is shared with the demo lane's
    # observer rows; fail-soft, observation never breaks the pass.
    try:
        from tradehub import kalshi_demo
        tracked: dict[str, dict] = {}
        for name, _v, _l in rule.SERIES:  # all three locked series
            tracked.update({d["target"]: d for d in _select(
                supa, DECISIONS,
                {"series": fifteen_tracking._BY_NAME[name]["series"]},
                order="close_time", desc=True, limit=1000)})
        kalshi_demo._settle_prod_fills(supa, tracked, now, summary)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"prod settle: {exc}")
    try:
        prod_keys = {(r["series"], r["target"], r.get("gate_version"))
                     for r in _select(supa, PROD_FILLS, {},
                                      order="created_at", desc=True,
                                      limit=1000)}
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"prod keys: {exc}")
        prod_keys = None

    halt = state.get("halt") or {}
    if halt.get("halted"):
        summary["halted"] = halt.get("reason")
        return summary

    balance = _balance_usd(portfolio)
    if balance is None:
        summary["errors"].append("balance unavailable; placements paused this pass")
        summary["balance_unavailable"] = True
        return summary
    summary["balance"] = balance
    if balance < FLOOR_USD:
        _halt(supa, state, "floor", now)
        summary["halted"] = "floor"
        _alert(supa, target="floor", event="floor_halt",
               title="Kalshi live pilot HALTED: balance floor",
               body=(f"The live balance read ${balance:.2f}, below the "
                     f"${FLOOR_USD:.2f} floor. The live lane is halted "
                     "and stays halted until Kevin re-enables it. "
                     "Real money account."),
               evidence={"balance": balance})
        return summary

    day_start = now.astimezone(ET).replace(hour=0, minute=0, second=0,
                                           microsecond=0)
    todays = [r for r in rows if _dt(r["created_at"]) >= day_start]
    session = now.astimezone(ET).date()
    settled_today = [r for r in rows if r["status"] == "settled"
                     and _dt(r["window_close"]).astimezone(ET).date() == session]
    session_loss = sum(-float(r["pnl"]) for r in settled_today
                       if (r.get("pnl") or 0) < 0)
    if session_loss >= DAILY_STOP_USD:
        summary["daily_stop"] = round(session_loss, 2)
        session = session.isoformat()
        _alert(supa, target=f"daily-stop:{session}", event="daily_stop",
               title="Kalshi live pilot: daily stop reached",
               body=(f"Settled live losses this ET session reached "
                     f"${session_loss:.2f} (stop: ${DAILY_STOP_USD:.2f}). "
                     "No new orders for the rest of the session. "
                     "Real money account."),
               evidence={"session": session, "session_loss": round(session_loss, 2)})
        return summary

    stage3 = bool((state.get("stage3") or {}).get("unlocked"))
    by_key = {(r["series"], r["target"]): r for r in rows}
    # Every claimed row counts (skips claim 0): a failed or pending claim
    # may have been accepted with its response lost.
    contracts_today = sum(int(r.get("contracts_requested") or 0)
                          for r in todays)
    notional_today = sum(
        int(r.get("contracts_requested") or 0)
        * float(r.get("live_ask") or r.get("frozen_quote") or 0)
        for r in todays)
    open_by_window: dict[str, dict] = {}
    for r in rows:
        if r["status"] in ("pending", "placed", "filled"):
            agg = open_by_window.setdefault(r["window_close"],
                                            {"contracts": 0, "cost": 0.0})
            n = int(r.get("contracts_filled") or r.get("contracts_requested") or 0)
            agg["contracts"] += n
            agg["cost"] += n * float(r.get("fill_price") or r.get("live_ask")
                                     or r.get("frozen_quote") or 0)

    decisions = [d for d in raw_open_decisions(supa, now)
                 if _dt(d["close_time"]) > now + CANCEL_BUFFER
                 and now - _dt(d["frozen_at"]) <= FRESHNESS
                 and (d["series"], d["target"]) not in by_key]
    summary["candidates"] = len(decisions)

    for d in decisions:
        base_row = {
            "series": d["series"], "target": d["target"], "lane": LANE,
            "ticker": d["ticker"], "side": d["side"],
            "model_prob": d.get("model_prob"),
            "frozen_quote": d["cost"], "frozen_at": d["frozen_at"],
            "window_close": d["close_time"],
            "client_order_id": f"kl-{d['ticker']}",
        }

        def skip(status: str, reason: str) -> None:
            row = {**base_row, "contracts_requested": 0,
                   "contracts_filled": 0, "status": status,
                   "skip_reason": reason,
                   "balance_at_sizing": balance}
            try:
                supa.table(ORDERS).insert(row).execute()
            except Exception:  # noqa: BLE001 -- a racing pass claimed it
                return
            by_key[(d["series"], d["target"])] = row
            summary["skipped_cap" if status == "skipped_cap"
                    else "skipped_no_depth"] += 1
            _alert(supa, target=d["target"], event=f"skip:{reason}",
                   title=f"Kalshi live skip: {d['ticker']} ({reason})",
                   body=(f"The live lane skipped {d['ticker']} "
                         f"({d['side']} @ frozen {d['cost']}): {reason}. "
                         "Nothing was placed. Real money account."),
                   evidence={"ticker": d["ticker"], "side": d["side"],
                             "reason": reason})

        cross = _live_cross_raw(portfolio, d["ticker"], d["side"],
                                d.get("model_prob"))
        if cross is None:
            skip("skipped_no_depth",
                 "edge_unmeasured" if d.get("model_prob") is None
                 else "live_ask_unavailable")
            continue
        price, edge = cross
        if edge < rule.MIN_EDGE - 1e-9:
            skip("skipped_no_depth", "edge_below_bar_at_live_ask")
            continue
        if price - float(d["cost"]) > max_slippage():
            skip("skipped_no_depth", "slippage_cap")
            continue

        contracts = size_contracts(balance, price, stage3)
        contracts = min(contracts, max_per_order(),
                        max_contracts_per_day() - contracts_today)
        if contracts < 1:
            skip("skipped_cap", "daily_contract_cap")
            continue
        room = max_notional_per_day_usd() - notional_today
        if contracts * price > room:
            contracts = int(room // price) if price > 0 else 0
            if contracts < 1:
                skip("skipped_cap", "daily_notional_cap")
                continue
        window = open_by_window.setdefault(d["close_time"],
                                           {"contracts": 0, "cost": 0.0})
        if balance < STAGE3_BALANCE:
            if window["contracts"] + contracts > WINDOW_CAP_CONTRACTS:
                contracts = WINDOW_CAP_CONTRACTS - window["contracts"]
                if contracts < 1:
                    skip("skipped_cap", "window_cap")
                    continue
        else:
            room_w = WINDOW_CAP_PCT * balance - window["cost"]
            if contracts * price > room_w:
                contracts = int(room_w // price) if price > 0 else 0
                if contracts < 1:
                    skip("skipped_cap", "window_cap")
                    continue

        _observe_prod_live(supa, d, base_row, contracts, prod_keys, summary)
        elapsed = timedelta(seconds=time.monotonic() - started)
        if now + elapsed > _dt(d["close_time"]) - CANCEL_BUFFER:
            skip("skipped_no_depth", "close_buffer")
            continue

        claim = {**base_row, "contracts_requested": contracts,
                 "contracts_filled": 0, "live_ask": price,
                 "balance_at_sizing": balance, "status": "pending"}
        try:
            data = supa.table(ORDERS).insert(claim).execute().data
            row = (data or [None])[0] or claim
        except Exception as exc:  # noqa: BLE001
            if "duplicate" in str(exc) or "unique" in str(exc).lower():
                continue  # a racing pass claimed it; never twice
            summary["errors"].append(f"claim {d['target']}: {exc}")
            continue
        by_key[(d["series"], d["target"])] = row
        # Reserve before the exchange write and keep it if create raises:
        # a response can be lost after acceptance.
        contracts_today += contracts
        notional_today += contracts * price
        window["contracts"] += contracts
        window["cost"] += contracts * price
        sent_at = now
        try:
            order = portfolio.create_order(
                ticker=d["ticker"], side=d["side"], count=contracts,
                limit_price_cents=int(round(price * 100)),
                client_order_id=base_row["client_order_id"],
                expiration_ts=int(_dt(d["close_time"]).timestamp()),
                time_in_force="immediate_or_cancel")
        except Exception as exc:  # noqa: BLE001 -- reconcile owns the claim
            summary["errors"].append(f"place {d['target']}: {exc}")
            if row.get("id") is not None:
                _update(supa, row, {"last_error": str(exc)[:500],
                                    "sent_at": _iso(sent_at)})
            _alert(supa, target=d["target"], event="placement_error",
                   title=f"Kalshi live placement error: {d['ticker']}",
                   body=(f"The live lane's create call for {d['ticker']} "
                         f"({d['side']} x{contracts} @ {price}) raised: "
                         f"{exc}. That is either an exchange refusal or a "
                         "response lost after acceptance; the claim stays "
                         "pending and reconciliation settles which. "
                         "Real money account."),
                   evidence={"ticker": d["ticker"], "side": d["side"],
                             "contracts": contracts, "live_ask": price,
                             "error": str(exc)[:300]})
            continue
        filled = 0
        try:
            filled = int(float(order.get("fill_count")))
        except (TypeError, ValueError):
            filled = 0
        latency = (sent_at - _dt(d["frozen_at"])).total_seconds()
        patch = {"kalshi_order_id": order.get("order_id"),
                 "sent_at": _iso(sent_at), "latency_s": round(latency, 1),
                 "contracts_filled": filled,
                 "status": "filled" if filled > 0 else "unfilled"}
        if filled > 0:
            fill_price, fee, flag = _executed(order, d["side"], filled, price)
            patch["fill_price"] = fill_price
            patch["fee_usd"] = fee
            patch["slippage"] = round(fill_price - float(d["cost"]), 4)
            if flag:
                patch["last_error"] = flag
        else:
            patch["skip_reason"] = "ioc_unfilled"
        if row.get("id") is not None:
            _update(supa, row, patch)
        row.update(patch)
        summary["placed"] += 1
        if filled > 0:
            summary["filled"] += 1
            _alert(supa, target=d["target"], event="fill",
                   title=f"Kalshi live fill: {d['ticker']}",
                   body=(f"Bought {filled} x {d['ticker']} ({d['side']}) "
                         f"at {patch['fill_price']} against a frozen {d['cost']} "
                         f"(slippage {patch['slippage']:+.4f}), fee "
                         f"${patch['fee_usd']:.2f}. Held to settlement. "
                         "Real money account."),
                   evidence={"ticker": d["ticker"], "side": d["side"],
                             "filled": filled,
                             "fill_price": patch["fill_price"],
                             "frozen_quote": d["cost"],
                             "fee_usd": patch["fee_usd"]})
        else:
            summary["unfilled"] += 1
    return summary


# -- the scoreboard ---------------------------------------------------------------

def build_scoreboard(supa, now: datetime, portfolio=None) -> dict:
    """The live lane's scoreboard block for the Kalshi page: balance
    and P&L, fill rate and mean slippage against the frozen paper
    price, live net per contract with its day-clustered low95 beside
    the paper twin's on the same windows, latency, gate and halt
    states. Read-only and fail-soft: an unapplied table or a missing
    key reads as the lane's state, never an error."""
    from tradehub.core.kalshi_live_portfolio import (
        check_live_available,
        live_enabled,
    )
    try:
        state = _get_state(supa)
    except Exception:  # noqa: BLE001 -- the board shows it, never breaks
        state = {"halt": {"halted": True, "reason": "state_unreadable"}}
    try:
        rows = _select(supa, ORDERS, {}, order="created_at", desc=True,
                       limit=1000)
    except Exception:  # noqa: BLE001 -- table not applied yet
        rows = []
    halt = state.get("halt") or {}
    balance = None
    if portfolio is not None:
        balance = _balance_usd(portfolio)
    elif check_live_available():
        try:
            from tradehub.core.kalshi_live_portfolio import (
                KalshiLivePortfolio,
            )
            balance = _balance_usd(KalshiLivePortfolio())
        except Exception:  # noqa: BLE001 -- a scoreboard read never breaks
            balance = None

    sent = [r for r in rows if r["status"] in SENT_STATUSES]
    filled_rows = [r for r in rows if int(r.get("contracts_filled") or 0) > 0]
    settled = [r for r in rows if r["status"] == "settled"]
    slips = [(float(r.get("fill_price") or r.get("live_ask")
                    or r["frozen_quote"])
              - float(r["frozen_quote"])) * 100.0 for r in filled_rows]
    live_items = _per_contract_items(settled)
    live_low = clustered_low95(live_items) if live_items else None
    filled_total = sum(int(r.get("contracts_filled") or 0) for r in settled)
    paper_items = [((r["series"], _dt(r["window_close"]).astimezone(ET)
                     .date().isoformat()),
                    float(r["paper_pnl"]) * 100.0)
                   for r in settled if r.get("paper_pnl") is not None]
    paper_low = clustered_low95(paper_items) if paper_items else None
    latencies = sorted(float(r["latency_s"]) for r in rows
                       if r.get("latency_s") is not None)
    gate1 = state.get("gate1") or {}
    gate2 = state.get("gate2") or {}
    return {
        "state": ("halted" if halt.get("halted")
                  else "live" if live_enabled() else "not_enabled"),
        "real_money": True,
        "enabled": live_enabled(),
        "halted": bool(halt.get("halted")),
        "halt_reason": halt.get("reason"),
        "balance": balance,
        "pnl_since_start": round(sum(float(r.get("pnl") or 0)
                                     for r in settled), 2),
        "decisions": len(sent),
        "fills": len(filled_rows),
        "fill_rate": (round(len(filled_rows) / len(sent), 4)
                      if sent else None),
        "mean_slippage_cents": (round(sum(slips) / len(slips), 2)
                                if slips else None),
        "settled": len(settled),
        "live_net_per_contract": (
            round(sum(float(r["pnl"]) for r in settled) / filled_total, 4)
            if filled_total else None),
        "live_low95_cents": (None if live_low is None
                             else round(live_low, 2)),
        "paper_net_per_contract": (
            round(sum(float(r["paper_pnl"]) for r in settled
                      if r.get("paper_pnl") is not None)
                  / len([r for r in settled
                         if r.get("paper_pnl") is not None]), 4)
            if any(r.get("paper_pnl") is not None for r in settled)
            else None),
        "paper_low95_cents": (None if paper_low is None
                              else round(paper_low, 2)),
        "latency_median_s": (latencies[len(latencies) // 2]
                             if latencies else None),
        "gates": {
            "execution": {"state": gate1.get("result", "pending"),
                          "fills": len(filled_rows), "bar": GATE1_FILLS,
                          "mean_slippage_cents":
                              gate1.get("mean_slippage_cents")},
            "edge": {"state": gate2.get("result", "pending"),
                     "settled": len(settled), "bar": GATE2_TRADES,
                     "low95_cents": gate2.get("low95_cents"),
                     "stage3_unlocked":
                         bool((state.get("stage3") or {}).get("unlocked"))},
        },
        "daily_stop_usd": DAILY_STOP_USD,
        "floor_usd": FLOOR_USD,
        "orders": [{
            "id": r.get("id"), "created_at": r.get("created_at"),
            "series": r["series"], "ticker": r["ticker"],
            "side": r["side"], "status": r["status"],
            "skip_reason": r.get("skip_reason"),
            "contracts_requested": r.get("contracts_requested"),
            "contracts_filled": r.get("contracts_filled") or 0,
            "frozen_quote": r.get("frozen_quote"),
            "live_ask": r.get("live_ask"),
            "fill_price": r.get("fill_price"),
            "fee_usd": r.get("fee_usd"), "outcome": r.get("outcome"),
            "pnl": r.get("pnl"), "paper_pnl": r.get("paper_pnl"),
            "window_close": r.get("window_close"),
        } for r in rows[:12]],
    }
