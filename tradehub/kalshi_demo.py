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
- One row per decision per lane in `kalshi_demo_orders`; the
  (series, target, gate_version) unique constraint is the
  never-order-twice guarantee.

The candidate lane (Step B.3, Claude's ruling 2026-11-13): beside the
live gate's lane, a second lane trades the same freeze-time decisions
when they also clear the preregistered v4-edge20-shadow dial (the edge
bar read from tradehub/fifteen_candidates, never restated here), at
half the live lane's caps and half its budget pct, each order tagged
gate_version = the candidate's name. It is a demo trial only: the
shadow record stays the measure, and lane trades never count toward
the candidate's promotion bar. Caps and tallies are per lane -- each
lane's day is counted from its own rows only.
- The live rule, the blend's frozen rows, shadow scoring and the Alpaca
  paper-order path are untouched: this module only reads them.

Execution (Kevin's call, 2026-11-14): orders cross at placement. The
record to that date showed the stale-quote signature -- every win a
partial fill, every loss a full fill -- from resting a limit at the
quote frozen ~9 minutes earlier. Placement now re-reads the live book,
re-validates the decision's edge at the live ask with the rule's own
net_edges against the lane's bar, sizes on the live ask, and sends an
immediate-or-cancel order at that ask (the row's limit_price is the
crossed ask, rewritten on every placement including a retried claim;
frozen_quote keeps the freeze-time quote). An unreadable
book, an unmeasured probability, or an edge that no longer clears the
bar is a skip with its reason, never a fallback to the frozen quote.
So is a cross whose live ask has run more than KALSHI_DEMO_MAX_SLIPPAGE
(default 0.03) above the frozen quote (skip_reason "slippage_cap",
Claude's post-merge review of #534): the edge is recomputed from a
minutes-old model_prob, and a run that large is news it has not heard.
The shadow record and the decisions it scores are unchanged.

Placement reliability (2026-11-13): every gated buy a lane selects
leaves a durable outcome in the same pass -- placed, skipped with its
reason, or `failed` with its reason (claim insert refused) -- with one
deliberate exception: a dead balance read writes no terminal row while
the signal is still fresh (an alert fires instead and the next pass
retries); the terminal `failed` row lands only on the decision's last
fresh pass, so a one-pass blip cannot kill a live signal through the
never-twice skip. A placement the exchange refuses records the refusal on
the claim row itself (`last_error`, migration 20261113000003, written
best-effort until it is applied), so at the cutoff the row closes as
`placement_failed`, never under the generic `placement_interrupted`
that means "no error recorded and nothing found on the exchange"
(2026-11-12's 00:52Z claim was refused HTTP 410 twice -- the retired V1
endpoint -- and written off as interrupted, the real error only in the
log). Drops and write-offs also go to the watcher_alerts outbox
(kind `kalshi_demo`, deduplicated per target + event), the delivery
channel Kevin already watches. Adoption by client_order_id sweeps the
resting, executed and canceled order lists, so an order that filled or
expired before the adopting pass is still found.
"""

from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import time

from tradehub import fifteen_candidates, fifteen_tracking, kalshi_prod_book
from tradehub import oil_fifteen_rule as rule
from tradehub.core.kalshi_portfolio import NotDemoHostError
from tradehub.fifteen_volregime import clustered_low95
from tradehub.journal.kalshi_linked import ticker_of
from tradehub.markets import quote_cents

SERIES = "KXNATGAS15M"
GAS_SERIES = tuple(s for s in rule.SERIES if s[0] == "natgas_15m")
ORDERS = "kalshi_demo_orders"
PROD_FILLS = "kalshi_prod_paper_fills"
DECISIONS = rule.DECISIONS_TABLE
TICKS = fifteen_tracking.TICKS_TABLE
ALERTS_TABLE = "watcher_alerts"
ALERT_KIND = "kalshi_demo"

PASS_INTERVAL = timedelta(minutes=5)    # the runner's cron cadence (2-57/5)
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


def max_slippage() -> float:
    """The most the live ask may sit ABOVE the frozen quote before the
    cross is refused (Claude's post-merge review of #534): the edge
    re-validation runs off a ~9-minute-old model_prob, so without a
    cap a frozen 0.40 could be crossed at 0.55. In price units
    (0.03 = 3 cents)."""
    return float(os.getenv("KALSHI_DEMO_MAX_SLIPPAGE", "0.03"))


def size_contracts(balance_usd: float, price: float, pct: float) -> int:
    """Kevin's 1% rule: floor(balance x pct / price), minimum 1 contract.

    Price-only, as Kevin stated it: the taker fee adds ~0.8% on top at
    typical quotes, which the PR flags rather than silently correcting.
    """
    if price <= 0 or balance_usd <= 0:
        return 0
    return max(1, math.floor(balance_usd * pct / price))


# -- lanes ----------------------------------------------------------------------
# The live gate's lane plus the Step B.3 candidate lane. A lane is a
# gate_version stamp, an optional extra edge bar over the gate's own
# decision, its own budget pct and daily caps, and its own
# client_order_id prefix (the live lane keeps the original `kd-` prefix
# so orders placed before the lane existed still adopt by id).

LANE_VERSION = "v4-edge20-shadow"


def _lane_min_edge() -> float | None:
    """The candidate lane's edge bar, read from the preregistered dial
    itself (fifteen_candidates) so the lane can never drift from the
    shadow it trials. None when the candidate has no gas dial."""
    candidate = fifteen_candidates.CANDIDATES.get(LANE_VERSION)
    if candidate is None:
        return None
    dial = candidate.dial_for(SERIES)
    return None if dial is None else dial.min_edge


def _lanes(live_version: str) -> list[dict]:
    lanes = [{
        "gate_version": live_version, "min_edge": None,
        "pct": budget_pct(), "cap_contracts": max_contracts_per_day(),
        "cap_loss": max_loss_per_day_usd(), "client_prefix": "kd-",
    }]
    min_edge = _lane_min_edge()
    if min_edge is not None:
        lanes.append({
            "gate_version": LANE_VERSION, "min_edge": min_edge,
            "pct": budget_pct() / 2,
            "cap_contracts": max(1, max_contracts_per_day() // 2),
            "cap_loss": max_loss_per_day_usd() / 2,
            "client_prefix": "kd-edge20-",
        })
    return lanes


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


def _live_cross(portfolio, ticker: str, side: str,
                model_prob: Any) -> tuple[float, float] | None:
    """(live ask, net edge there) for the chosen side, from the live
    book, with the edge recomputed by the rule's own net_edges -- the
    cross-at-placement re-validation. None when the book or the
    probability cannot be read: placement never falls back to the
    frozen quote (resting at a ~9-minute-old quote was the stale-quote
    adverse selection this replaces: partial fills on every win, full
    fills on every loss)."""
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

    edges = rule.net_edges(float(model_prob), yes_ask=dollars("yes_ask"),
                           yes_bid=dollars("yes_bid"))
    if edges is None:
        return None
    if side == "yes":
        return dollars("yes_ask"), edges[0]
    no_ask = dollars("no_ask")
    if no_ask is None:
        return None
    return no_ask, edges[1]


class _ProdBook:
    """The `_live_cross` surface over one production market read: the
    cross rule, the edge recomputation and the quote mapping are the
    demo's own; only the book differs. `get_market_data` is a pure
    function of the frozen read -- this adapter has no order surface
    at all, and the reader behind it (kalshi_prod_book) can only GET."""

    def __init__(self, market: dict):
        self._market = market

    def get_market_data(self, ticker: str) -> dict:
        return {"market": self._market}


def _observe_prod(supa, lane: dict, d: dict, base_row: dict,
                  balance: float, prod_keys: set, summary: dict) -> None:
    """The would-have-filled record for one decision (Kevin's ruling,
    2026-11-17): read the PRODUCTION book for the decision's ticker and
    record what the real book would have done -- the same cross rule,
    edge bar and slippage cap as the demo cross, the same 1% sizing at
    the lane's pct, settled later from the window's outcome.
    Observation only: nothing here places, and a failed or empty
    production read records nothing (an unreadable book is no
    measurement). One record per (series, target, gate_version): the
    first observation stands, so later passes skip it via prod_keys."""
    key = (SERIES, base_row["target"], lane["gate_version"])
    if prod_keys is None or key in prod_keys:
        return
    try:
        market = kalshi_prod_book.read_market(base_row["ticker"])
        if market is None:
            return
        quotes = quote_cents(market)
        if all(v is None for v in quotes.values()):
            # An incomplete response (no readable quote at all) is not a
            # measured book: record nothing, the same as an unreadable book,
            # rather than a no_cross row claiming an empty side. A readable
            # book with an empty side is still no_cross below.
            return

        def dollars(field: str) -> float | None:
            cents = quotes.get(field)
            return None if cents is None else cents / 100.0

        row: dict[str, Any] = {
            "series": SERIES, "target": base_row["target"],
            "gate_version": lane["gate_version"],
            "ticker": base_row["ticker"], "side": d["side"],
            "model_prob": d.get("model_prob"),
            "frozen_quote": base_row.get("frozen_quote"),
            "prod_yes_bid": dollars("yes_bid"),
            "prod_yes_ask": dollars("yes_ask"),
            "prod_no_bid": dollars("no_bid"),
            "prod_no_ask": dollars("no_ask"),
            "ask_size": None, "would_price": None, "contracts": None,
            # Claude's review of the prod-book PR: an empty side (the
            # cross finds nothing) is its own status, not a no-edge --
            # "no_edge_at_ask" is reserved for a real cross whose edge
            # falls under the bar (set below).
            "status": "no_cross",
            "window_close": base_row["window_close"],
        }
        cross = _live_cross(_ProdBook(market), base_row["ticker"],
                            d["side"], d.get("model_prob"))
        if cross is not None:
            price, edge = cross
            row["would_price"] = price
            contracts = size_contracts(balance, price, lane["pct"])
            row["contracts"] = contracts
            bar = (lane["min_edge"] if lane["min_edge"] is not None
                   else rule.MIN_EDGE)
            frozen = base_row.get("frozen_quote")
            if edge < bar - 1e-9:
                row["status"] = "no_edge_at_ask"
            elif frozen is not None and price - float(frozen) > max_slippage():
                row["status"] = "slippage_cap"
            else:
                size = kalshi_prod_book.read_ask_size(
                    base_row["ticker"], d["side"], price)
                if size is None:
                    # Unmeasured depth is not an observation: no row, the
                    # same as an unreadable book, so it neither takes the key
                    # as a rejection nor counts in the fill rate (CodeRabbit
                    # on #560). A pass that re-reads the decision (a pending
                    # claim) can still record it.
                    return
                row["ask_size"] = size
                # A measured-but-small book is thin, only a measured book
                # that covers the size is would_fill (unmeasured returned above).
                row["status"] = ("thin" if size < contracts
                                 else "would_fill")
        supa.table(PROD_FILLS).insert(row).execute()
        prod_keys.add(key)
        summary["prod_recorded"] += 1
    except Exception as exc:  # noqa: BLE001 -- observation never breaks the pass
        summary["errors"].append(
            f"prod observe {base_row['target']}: {exc}")


def _unsettled_would_fills(supa, page: int = 1000) -> list[dict]:
    """Every would_fill row still without an outcome, newest first, read in
    pages: settled rows are excluded in the query, and paging means a run of
    1,000 newer rows that cannot settle yet never hides an older one
    (CodeRabbit on #560)."""
    out: list[dict] = []
    while True:
        rows = (supa.table(PROD_FILLS).select("*").eq("status", "would_fill")
                .is_("outcome", "null").order("created_at", desc=True)
                .range(len(out), len(out) + page - 1).execute().data) or []
        out.extend(rows)
        if len(rows) < page:
            return out


def _settle_prod_fills(supa, tracked: dict, now: datetime,
                       summary: dict) -> None:
    """Settle would_fill rows whose window outcome has landed, at the
    recorded would-have price, through the rule's own fee-netted pnl --
    the same settlement the shadow record gets."""
    for r in _unsettled_would_fills(supa):
        if r.get("outcome") is not None or r.get("would_price") is None:
            continue
        d = tracked.get(r["target"])
        outcome = d.get("outcome") if d else None
        if outcome is None:
            continue
        pnl = round(int(r.get("contracts") or 0)
                    * rule.pnl(r["side"], float(r["would_price"]),
                               int(outcome)), 4)
        (supa.table(PROD_FILLS)
         .update({"outcome": int(outcome), "pnl": pnl,
                  "settled_at": _iso(now)})
         .eq("id", r["id"]).execute())
        summary["prod_settled"] += 1


def _dead_book_series(rows: list[dict],
                      now: datetime) -> tuple[str, int] | None:
    """(series, count) when every demo decision outcome recorded in
    today's ET session for the series is a live_ask_unavailable skip:
    the demo exchange's book read as empty all session (Kevin's ruling,
    2026-11-17). Any other terminal outcome -- a placement, a cap, a
    different skip -- breaks the read: the book was reachable then."""
    day = now.astimezone(ET).date()

    def created_day(r: dict):
        try:
            return _dt(r["created_at"]).astimezone(ET).date()
        except Exception:  # noqa: BLE001 -- an unstamped row is not today's
            return None

    todays = [r for r in rows if r.get("series") == SERIES
              and created_day(r) == day]
    unavail = [r for r in todays if r["status"] == "skipped_no_depth"
               and r.get("skip_reason") == "live_ask_unavailable"]
    if not unavail:
        return None
    unavail_ids = {r.get("id") for r in unavail}
    others = [r for r in todays if r.get("id") not in unavail_ids
              and r["status"] != "pending"]
    if others:
        return None
    return SERIES, len(unavail)


def _order_count(order: dict, key: str) -> int | None:
    """A V2 order count (fixed-point string or number), or None when
    the response does not carry it."""
    try:
        return int(float(order.get(key)))
    except (TypeError, ValueError):
        return None


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
        "failed": 0, "cancelled": 0, "settled": 0, "decision_mismatch": 0,
        "prod_recorded": 0, "prod_settled": 0,
        "errors": [],
    }
    try:
        portfolio.assert_demo_host()
    except NotDemoHostError as exc:
        summary["refused"] = str(exc)
        return summary

    version, _since = fifteen_tracking._live_gate(supa)
    summary["gate_version"] = version

    rows = _select(supa, ORDERS, {}, order="created_at", desc=True, limit=500)
    by_key = {(r["target"], r.get("gate_version")): r for r in rows}

    tracked = _tracked_decisions(supa)
    summary["decision_mismatch"] = len(decision_mismatches(rows, tracked))
    _reconcile(supa, portfolio, rows, now, summary, tracked)
    # The production-book record is observation only: a failure here must
    # never stop the demo lanes below (CodeRabbit on #560). Unsettled rows
    # keep outcome NULL and are picked up again next pass.
    try:
        _settle_prod_fills(supa, tracked, now, summary)
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"prod settle: {exc}")
    try:
        prod_keys = {(r["series"], r["target"], r.get("gate_version"))
                     for r in _select(supa, PROD_FILLS, {},
                                      order="created_at", desc=True,
                                      limit=1000)}
    except Exception as exc:  # noqa: BLE001
        summary["errors"].append(f"prod keys: {exc}")
        prod_keys = None  # unknown: skip observing this pass rather than double-record

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

    # Each lane trades its own slice of the same fresh decisions under
    # its own caps and tallies; the candidate lane's slice is the subset
    # that also clears its preregistered edge bar (an unmeasured edge is
    # not a cleared bar).
    day_start = _day_start_et(now)
    summary["lanes"] = {}
    for lane in _lanes(version):
        lane_fresh = fresh
        if lane["min_edge"] is not None:
            lane_fresh = [d for d in fresh
                          if d.get("edge_net") is not None
                          and float(d["edge_net"]) >= lane["min_edge"]]
        lane_summary = {"candidates": len(lane_fresh), "placed": 0,
                        "skipped_cap": 0, "skipped_no_depth": 0, "failed": 0}
        summary["lanes"][lane["gate_version"]] = lane_summary
        _trade_lane(supa, portfolio, now, lane, lane_fresh, rows, by_key,
                    day_start, summary, lane_summary, prod_keys)

    # Dead-book alert (Kevin's ruling, 2026-11-17): if the whole ET
    # session's decisions for the series skipped on an unavailable live
    # ask, the demo book is empty -- say so once per series per session
    # (the alert's dedupe key carries the session date). Read fresh:
    # this pass's own skips count.
    rows_after = _select(supa, ORDERS, {}, order="created_at",
                         desc=True, limit=500)
    dead = _dead_book_series(rows_after, now)
    if dead is not None:
        series_name, count = dead
        session = now.astimezone(ET).date().isoformat()
        _alert_drop(
            supa, target=f"dead-book:{series_name}:{session}",
            version=None, event="dead_book",
            title=f"Kalshi demo book empty: {series_name}",
            body=(f"Every demo decision so far in the {session} ET "
                  f"session for {series_name} ({count}) skipped with "
                  "live_ask_unavailable: the demo exchange's book for "
                  "the series is empty, while production quotes "
                  "normally. The lane keeps deciding and skipping "
                  "cleanly, and the would-have-filled record against "
                  "the production book carries the measurement until "
                  "the demo book returns. Demo account; nothing was "
                  "placed."),
            evidence={"series": series_name, "session_date": session,
                      "count": count})
    return summary


def _trade_lane(supa, portfolio, now: datetime, lane: dict,
                fresh: list[dict], rows: list[dict], by_key: dict,
                day_start: datetime, summary: dict,
                lane_summary: dict, prod_keys: set) -> None:
    """One lane's placements for this pass. Daily-cap state is the
    lane's own: only rows stamped with the lane's gate_version count
    toward its caps, tracked in memory as this pass places."""
    version = lane["gate_version"]
    pct = lane["pct"]
    cap_contracts = lane["cap_contracts"]
    cap_loss = lane["cap_loss"]

    todays = [r for r in rows if r.get("gate_version") == version
              and _dt(r["created_at"]) >= day_start]
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

    balance_dead = False
    for d in fresh:
        target = d["target"]
        existing = by_key.get((target, version))
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
        base_row = {
            "series": SERIES, "target": target,
            "ticker": d.get("ticker") or ticker_of(target),
            "side": d["side"], "gate_version": version,
            "limit_price": cost, "frozen_quote": cost,
            "window_close": _iso(_dt(d["close_time"])),
            "client_order_id": f"{lane['client_prefix']}{d.get('ticker') or ticker_of(target)}",
        }
        # Every decision this lane selected leaves a durable outcome in
        # this same pass. A dead balance read used to abandon the rest
        # of the lane with nothing but a log line; now it alerts (and,
        # on the decision's last fresh pass, records the terminal
        # `failed` row) -- see _balance_failure. When a claim is already
        # pending, the error is noted on that claim instead: the claim
        # itself is its durable record and is never overwritten by a
        # terminal state.
        if balance_dead:
            _balance_failure(supa, existing, base_row, summary, lane_summary, now)
            continue
        balance = _balance_usd(portfolio)
        if balance is None:
            balance_dead = True
            summary["errors"].append("balance unavailable; placements paused this pass")
            _balance_failure(supa, existing, base_row, summary, lane_summary, now)
            continue
        # The would-have-filled observation rides the same moment and
        # the same balance read; it never affects the placement below.
        _observe_prod(supa, lane, d, base_row, balance, prod_keys, summary)
        # Cross-at-placement (Kevin's call, 2026-11-14): never rest at
        # the frozen quote. Re-read the live book, re-validate the
        # decision's edge at the live ask against the lane's bar, and
        # size on the live ask; the order crosses IOC at that ask.
        cross = _live_cross(portfolio, base_row["ticker"], d["side"],
                            d.get("model_prob"))
        if cross is None:
            _skip(supa, existing, {
                **base_row, "contracts": 0, "ask_size": None,
                "status": "skipped_no_depth",
                "skip_reason": ("edge_unmeasured" if d.get("model_prob") is None
                                else "live_ask_unavailable")})
            summary["skipped_no_depth"] += 1
            lane_summary["skipped_no_depth"] += 1
            continue
        price, edge_at_ask = cross
        bar = lane["min_edge"] if lane["min_edge"] is not None else rule.MIN_EDGE
        if edge_at_ask < bar - 1e-9:
            _skip(supa, existing, {
                **base_row, "contracts": 0, "ask_size": None,
                "status": "skipped_no_depth",
                "skip_reason": "edge_below_bar_at_live_ask"})
            summary["skipped_no_depth"] += 1
            lane_summary["skipped_no_depth"] += 1
            continue
        # Slippage cap (Claude's post-merge review of #534): the edge
        # above was recomputed from a ~9-minute-old model_prob, so the
        # cross also refuses when the live ask has run too far above
        # the quote the decision froze at -- the move itself is the
        # news the frozen probability has not heard.
        frozen = base_row.get("frozen_quote")
        if frozen is not None and price - float(frozen) > max_slippage():
            _skip(supa, existing, {
                **base_row, "contracts": 0, "ask_size": None,
                "status": "skipped_no_depth",
                "skip_reason": "slippage_cap"})
            summary["skipped_no_depth"] += 1
            lane_summary["skipped_no_depth"] += 1
            continue
        base_row["limit_price"] = price
        depth = ask_size_at(supa, SERIES, d["close_time"], d["side"], now)
        if depth is not None and depth < 1:
            _skip(supa, existing, {**base_row, "contracts": 0, "ask_size": depth,
                                   "status": "skipped_no_depth"})
            summary["skipped_no_depth"] += 1
            lane_summary["skipped_no_depth"] += 1
            continue
        contracts = size_contracts(balance, price, pct)
        if contracts_today >= cap_contracts:
            _skip(supa, existing, {**base_row, "contracts": 0, "ask_size": depth,
                                   "status": "skipped_cap",
                                   "skip_reason": "daily_contract_cap"})
            summary["skipped_cap"] += 1
            lane_summary["skipped_cap"] += 1
            continue
        contracts = min(contracts, cap_contracts - contracts_today)
        if loss_used + contracts * price > cap_loss:
            _skip(supa, existing, {**base_row, "contracts": 0, "ask_size": depth,
                                   "status": "skipped_cap",
                                   "skip_reason": "daily_loss_cap"})
            summary["skipped_cap"] += 1
            lane_summary["skipped_cap"] += 1
            continue

        expires = _dt(d["close_time"]) - CANCEL_BUFFER
        claim = {**base_row, "contracts": contracts, "contracts_filled": 0,
                 "ask_size": depth, "balance_at_sizing": balance, "budget_pct": pct,
                 "expires_at": _iso(expires), "status": "pending"}
        row = existing or _insert(supa, claim, summary)
        if row is None:
            # The claim insert itself was refused. A bare `continue`
            # here was a silent drop: the decision existed only in this
            # pass's log line. Record the failure durably and alert --
            # unless the refusal is the unique key saying the row
            # already exists: a racing pass claimed it between this
            # pass's read and its insert. That is not a dropped signal,
            # so it earns no `failed` record and no alert; the row is
            # picked up and the next pass treats it as its own.
            detail = summary.pop("_claim_error", "claim insert refused")
            if _is_unique_violation(detail):
                summary["errors"] = [
                    e for e in summary["errors"]
                    if e != f"claim {target}: {detail}"]
                found = _find_row(supa, target, version)
                if found is not None:
                    by_key[(target, version)] = found
                    continue
            failed_row = _record_failure(
                supa, base_row, reason="claim_failed", detail=detail,
                summary=summary, lane_summary=lane_summary)
            if failed_row is not None:
                by_key[(target, version)] = failed_row
            continue
        by_key[(target, version)] = row
        try:
            order = portfolio.create_order(
                ticker=base_row["ticker"], side=d["side"], count=contracts,
                limit_price_cents=int(round(price * 100)),
                client_order_id=base_row["client_order_id"],
                expiration_ts=int(expires.timestamp()),
                time_in_force="immediate_or_cancel")
        except Exception as exc:  # noqa: BLE001 -- leave pending; reconcile owns it
            summary["errors"].append(f"place {target}: {exc}")
            # The error is recorded on the claim itself and alerted now,
            # not reconstructed (wrongly) at the cutoff. The alert does
            # not call it a refusal: a create that raises may be one, or
            # a response lost after the exchange accepted the order --
            # the two look identical from here, and adoption by
            # client_order_id, not this alert, settles which it was.
            _note_error(supa, row, f"place: {exc}")
            _alert_drop(
                supa, target=target, version=version, event="placement_failed",
                title=f"Kalshi demo placement error: {base_row['ticker']}",
                body=(f"The demo runner's create call for "
                      f"{base_row['ticker']} ({d['side']} x{contracts} @ "
                      f"{price}) raised: {exc}. That is either an exchange "
                      "refusal (nothing was placed) or a response lost "
                      "after acceptance. The claim stays pending: the "
                      "next pass adopts the order by client_order_id if "
                      "the exchange holds it, and the placement is "
                      "retried while the window is open. Demo account."),
                evidence={"ticker": base_row["ticker"], "side": d["side"],
                          "contracts": contracts, "limit_price": price,
                          "error": str(exc)[:300]})
            continue
        if _order_count(order, "fill_count") == 0 and \
                _order_count(order, "remaining_count") == 0:
            # The cross found nothing at the live ask and the IOC order
            # is already gone from the book: the row closes now instead
            # of resting as a phantom until the cutoff sweep. Nothing
            # was ever at risk, so the loss tally does not move.
            _update(supa, row, {"kalshi_order_id": order.get("order_id"),
                                "status": "cancelled",
                                "skip_reason": "ioc_unfilled",
                                "contracts": contracts,
                                "limit_price": price,
                                "balance_at_sizing": balance,
                                "budget_pct": pct, "ask_size": depth,
                                "expires_at": _iso(expires)})
            contracts_today += contracts
        else:
            _update(supa, row, {"kalshi_order_id": order.get("order_id"),
                                "status": "resting", "contracts": contracts,
                                "limit_price": price,
                                "balance_at_sizing": balance,
                                "budget_pct": pct, "ask_size": depth,
                                "expires_at": _iso(expires)})
            contracts_today += contracts
            loss_used += contracts * price
        summary["placed"] += 1
        lane_summary["placed"] += 1


def _note_error(supa, row: dict, message: str) -> None:
    """Best-effort: persist WHY a placement failed on the order row
    itself (the `last_error` column, migration 20261113000003). Until
    that migration is applied the write is refused by PostgREST and
    silently no-ops -- the journal store's missing-column hazard in
    reverse: recording must never break the pass it records. The alert
    outbox carries the same error from day one; this column puts it on
    the row the demo tab displays."""
    try:
        _update(supa, row, {"last_error": str(message)[:500]})
    except Exception:  # noqa: BLE001 -- column not deployed yet, or DB hiccup
        pass


def _alert_drop(supa, *, target: str, version: str | None, event: str,
                title: str, body: str,
                evidence: dict[str, Any] | None = None) -> bool:
    """One pending watcher_alerts row for a dropped or written-off demo
    placement, deduplicated on (target, gate_version, event) across all
    rows ever written -- modeled on gate_alerts.write_gate_alert (same
    outbox, same poller delivery), with its own kind: a drop is
    announced once, however many passes observe it. Fail-soft: a missed
    alert must never break the pass."""
    try:
        rows = (supa.table(ALERTS_TABLE).select("id,evidence")
                .eq("kind", ALERT_KIND).execute().data) or []
        for r in rows:
            ev = r.get("evidence") or {}
            if (ev.get("target") == target and ev.get("gate_version") == version
                    and ev.get("event") == event):
                return False
        ev = dict(evidence or {})
        ev.update({"target": target, "gate_version": version, "event": event})
        supa.table(ALERTS_TABLE).insert({
            "kind": ALERT_KIND, "watch_id": None, "family": "kalshi_demo",
            "title": title, "body": body, "evidence": ev, "status": "pending",
        }).execute()
        return True
    except Exception:  # noqa: BLE001
        return False


def _record_failure(supa, base_row: dict, *, reason: str, detail: str,
                    summary: dict, lane_summary: dict) -> dict | None:
    """The durable outcome for a decision a lane selected but could not
    even claim (balance read down, claim insert refused): a terminal
    `failed` row under the same never-twice key, carrying its reason,
    plus the outbox alert -- so the signal is on the record instead of
    existing only in the run's log. Returns the row when it landed."""
    row = None
    try:
        data = supa.table(ORDERS).insert(
            {**base_row, "contracts": 0, "status": "failed",
             "skip_reason": reason}).execute().data
        row = (data or [None])[0]
    except Exception:  # noqa: BLE001 -- even the failure record can be refused;
        row = None  # the alert below is the second channel
    if row is not None and detail:
        _note_error(supa, row, detail)
    record_line = (
        "It is recorded as failed on the demo order record."
        if row is not None else
        "The failure row itself could not be written, so this alert "
        "is the only record of the drop.")
    _alert_drop(
        supa, target=base_row["target"], version=base_row["gate_version"],
        event=reason,
        title=f"Kalshi demo dropped a signal: {base_row['ticker']}",
        body=(f"The demo runner selected this gated buy "
              f"({base_row['side']} @ {base_row['limit_price']}) but could "
              f"not place it: {reason} -- {detail}. {record_line} "
              "Demo account; nothing was placed."),
        evidence={"ticker": base_row["ticker"], "side": base_row["side"],
                  "limit_price": base_row["limit_price"], "detail": detail})
    summary["failed"] += 1
    lane_summary["failed"] += 1
    return row


def _balance_failure(supa, existing: dict | None, base_row: dict,
                     summary: dict, lane_summary: dict,
                     now: datetime) -> None:
    """The balance-unavailable outcome for one selected decision. A
    pending claim is already the durable record -- note the error on it
    and leave its state alone (it may still place next pass). With no
    claim yet, a terminal `failed` row would end the decision for good
    (the never-twice skip checks for exactly that row), so a one-pass
    balance blip must not write one while the signal is still fresh:
    alert only and let the next pass retry. The terminal record lands
    on the decision's last fresh pass -- when its cutoff falls within
    one more runner interval, no later pass will select it again."""
    if existing is not None:
        # Note the outage only on a claim carrying no error yet: the
        # recorded error is what the cutoff write-off quotes, and a
        # placement refusal already on the claim (an HTTP 410, say)
        # must not be replaced by a later, lesser balance failure.
        if not existing.get("last_error"):
            _note_error(supa, existing, "balance unavailable")
        return
    last_chance = (_dt(base_row["window_close"]) - CANCEL_BUFFER
                   <= now + PASS_INTERVAL)
    if not last_chance:
        _alert_drop(
            supa, target=base_row["target"],
            version=base_row["gate_version"], event="balance_unavailable",
            title=f"Kalshi demo balance read down: {base_row['ticker']}",
            body=(f"The demo runner selected this gated buy "
                  f"({base_row['side']} @ {base_row['limit_price']}) but "
                  "the balance read failed, so sizing is impossible and "
                  "nothing was placed this pass. No terminal record is "
                  "written while the signal is fresh -- the next pass "
                  "retries it. Demo account; nothing was placed."),
            evidence={"ticker": base_row["ticker"], "side": base_row["side"],
                      "limit_price": base_row["limit_price"],
                      "detail": "balance read failed; placement deferred "
                                "to the next pass"})
        return
    _record_failure(supa, base_row, reason="balance_unavailable",
                    detail="balance read failed; sizing is impossible "
                           "without it, so nothing was placed",
                    summary=summary, lane_summary=lane_summary)


def _find_by_client_order_id(portfolio, client_order_id: str) -> dict | None:
    """The exchange's own record of an order we may already have placed.

    Sweeps the default read, then the executed and canceled lists: an
    order that filled, expired or was canceled before the adopting pass
    may not appear in the default (resting) view, and missing it would
    write a real order off as never placed."""
    get_orders = getattr(portfolio, "get_orders", None)
    if get_orders is None:
        return None
    for status in (None, "executed", "canceled"):
        try:
            orders = get_orders(status=status) if status else get_orders()
        except Exception:  # noqa: BLE001 -- unreadable is not absent; try the next view
            continue
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


def _is_unique_violation(detail: str) -> bool:
    """True when a refused insert is the (series, target, gate_version)
    unique key answering -- the row already exists -- rather than a
    refusal of the write itself. PostgREST surfaces the Postgres
    wording and the 23505 code; either marks it."""
    return "duplicate key" in detail or "23505" in detail


def _find_row(supa, target: str, version: str) -> dict | None:
    """The order row for one (target, gate_version) key, re-read after
    a racing pass may have claimed it mid-pass."""
    for r in _select(supa, ORDERS, {"target": target}, limit=50):
        if r.get("gate_version") == version:
            return r
    return None


def _insert(supa, row: dict, summary: dict) -> dict | None:
    try:
        data = supa.table(ORDERS).insert(row).execute().data
    except Exception as exc:  # noqa: BLE001 -- unique (series, target) backstop
        summary["errors"].append(f"claim {row['target']}: {exc}")
        summary["_claim_error"] = str(exc)  # popped by the failure recorder
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

def _fills_by_order(portfolio) -> dict[str, dict] | None:
    """order_id -> {count, avg_price (dollars, bought side), first_ts}.

    None when the fills read itself fails: a failed read is not an
    empty book, and the caller must not draw zero-fill conclusions
    (least of all terminal ones) from it."""
    out: dict[str, dict] = {}
    try:
        fills = portfolio.get_fills(limit=200)
    except Exception:  # noqa: BLE001
        return None
    for f in fills or []:
        oid = f.get("order_id")
        if not oid:
            continue
        count = float(f.get("count_fp") or f.get("count") or 0)
        if count <= 0:
            continue
        # V2 fills: outcome_side + *_price_dollars; legacy: side + cents.
        yes_side = (f.get("outcome_side") or f.get("side")) == "yes"
        dollars = f.get("yes_price_dollars" if yes_side else "no_price_dollars")
        if dollars is not None:
            cents = float(dollars) * 100.0
        else:
            cents = f.get("yes_price") if yes_side else f.get("no_price")
            if cents is None:
                cents = f.get("yes_price", 0)
        agg = out.setdefault(oid, {"count": 0.0, "cost": 0.0, "first_ts": None})
        agg["count"] += count
        agg["cost"] += float(cents) * count
        ts = f.get("created_time") or f.get("created_ts")
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
    fills_known = fills is not None
    fills = fills or {}
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
                # Truthful terminal label: a claim carrying a recorded
                # refusal was REFUSED (placement_failed); only a claim
                # with no recorded error and nothing on the exchange is
                # an interruption -- a lost response or a killed pass.
                # Either way the write-off is alerted: a dropped claim
                # must not sit silently in the table.
                reason = ("placement_failed" if row.get("last_error")
                          else "placement_interrupted")
                _update(supa, row, {"status": "cancelled",
                                    "skip_reason": reason})
                summary["cancelled"] += 1
                _alert_drop(
                    supa, target=row["target"],
                    version=row.get("gate_version"), event="written_off",
                    title=f"Kalshi demo claim written off: {row['ticker']}",
                    body=(f"A pending demo claim for {row['ticker']} "
                          f"reached its cutoff with no order on the "
                          f"exchange and was closed as {reason}."
                          + (f" Recorded error: {row['last_error']}"
                             if row.get("last_error") else
                             " No placement error was recorded; the "
                             "placement response was lost or the pass was "
                             "interrupted.")
                          + " Demo account; nothing was placed."),
                    evidence={"ticker": row["ticker"], "skip_reason": reason,
                              "last_error": row.get("last_error")})
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
            if fills_known and filled == 0 and row["status"] == "resting":
                # Only a fills read that SUCCEEDED may close the row as
                # cancelled: on a failed read an executed order would be
                # written off with zero fills, and `cancelled` is not an
                # open status, so no later pass would ever recover them.
                # The row stays resting and the next pass rereads.
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


def _lane_summaries(rows: list[dict]) -> list[dict]:
    """Per-lane record for the demo tab: each gate_version's orders on
    their own line, so the candidate lane's trial never pools into the
    live lane's figures. The candidate lane sorts last."""
    by_version: dict[str, list[dict]] = {}
    for r in rows:
        by_version.setdefault(r.get("gate_version") or "unstamped", []).append(r)
    out = []
    for version, lane_rows in by_version.items():
        settled = [r for r in lane_rows if r["status"] == "settled"]
        filled = sum(int(r.get("contracts_filled") or 0) for r in settled)
        pnl = round(sum(float(r.get("settlement_pnl") or 0) for r in settled), 2)
        wins = sum(1 for r in settled if float(r.get("settlement_pnl") or 0) > 0)
        out.append({
            "gate_version": version,
            "orders": len(lane_rows),
            "settled": len(settled),
            "win_rate": round(wins / len(settled), 4) if settled else None,
            "pnl": pnl,
            "pnl_per_contract": (round(pnl / filled, 4) if filled else None),
        })
    out.sort(key=lambda lane: (lane["gate_version"] == LANE_VERSION,
                               lane["gate_version"]))
    return out


def _prod_lane_summaries(supa) -> list[dict]:
    """Per-lane would-have-filled record against the production book:
    how many decisions were observed, how many the real book would
    have filled, and the settled fills' per-contract P&L with its
    day-clustered low95 in cents (the house estimator, clusters keyed
    by series + ET settlement day)."""
    rows = _select(supa, PROD_FILLS, {}, order="created_at",
                   desc=True, limit=1000)
    by_version: dict[str, list[dict]] = {}
    for r in rows:
        by_version.setdefault(r.get("gate_version") or "unstamped",
                              []).append(r)
    out = []
    for version, lane_rows in by_version.items():
        fills = [r for r in lane_rows if r["status"] == "would_fill"]
        settled = [r for r in fills if r.get("pnl") is not None]
        contracts = sum(int(r.get("contracts") or 0) for r in settled)
        pnl = sum(float(r["pnl"]) for r in settled)
        # One item per contract, so the low95's mean is the contract-weighted
        # pnl_per_contract the headline shows (Claude's #560 review, :1277).
        items = [((r["series"], _dt(r["window_close"]).astimezone(ET)
                   .date().isoformat()),
                  float(r["pnl"]) / int(r["contracts"]) * 100.0)
                 for r in settled if int(r.get("contracts") or 0) > 0
                 for _ in range(int(r["contracts"]))]
        low = clustered_low95(items) if items else None
        out.append({
            "gate_version": version,
            "recorded": len(lane_rows),
            "would_fill": len(fills),
            "fill_rate": (round(len(fills) / len(lane_rows), 4)
                          if lane_rows else None),
            "settled": len(settled),
            "pnl_per_contract": (round(pnl / contracts, 4)
                                 if contracts else None),
            "low95_cents": None if low is None else round(low, 2),
        })
    out.sort(key=lambda lane: (lane["gate_version"] == LANE_VERSION,
                               lane["gate_version"]))
    return out


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
        "lanes": _lane_summaries(rows),
        "health": ([f"demo book empty: {_dead_book_series(rows, now)[0]}"]
                   if _dead_book_series(rows, now) else []),
        "prod_book": _prod_lane_summaries(supa),
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
                # Missed = selected placements that never reached the
                # exchange: interrupted claims, refused placements
                # written off at the cutoff, and `failed` rows (balance
                # read down, claim insert refused).
                "missed": sum(1 for r in rows
                              if r["status"] == "failed"
                              or (r["status"] == "cancelled"
                                  and r.get("skip_reason") in
                                  ("placement_interrupted",
                                   "placement_failed"))),
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
            "last_error": r.get("last_error"),
            "fill_price": r.get("fill_price"), "filled_at": r.get("filled_at"),
            "window_close": r["window_close"], "outcome": r.get("outcome"),
            "settlement_pnl": r.get("settlement_pnl"),
        } for r in rows],
        "note": NOTE,
    }
