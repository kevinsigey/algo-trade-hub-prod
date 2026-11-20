"""Portfolio routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from tradehub.api.schemas import (
    Position, PnLSummary,
)
from tradehub.api.dependencies import get_supabase
from tradehub.api import admin
from tradehub.workshop import store as workshop_store


from tradehub.api.shared import (
    _table_fault,
)

log = logging.getLogger(__name__)

router = APIRouter()


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3: /api/positions
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/positions", response_model=List[Position], tags=["Portfolio"])
async def get_positions(
    engine: Optional[str] = Query(None, description="Filter by engine name"),
    supabase=Depends(get_supabase),
):
    """Open paper trade positions from Supabase.

    The ledger this reads (`paper_trades`) is created by migration 20260416000011 and has no
    writer, because the product is suggest-only (spec section 6): an empty list is the true state,
    not a fault. A table that is genuinely absent is reported as such rather than as a raw
    PostgREST dump -- a 500 here is what put a red "unavailable" on the War Room, and the reader
    could not tell a missing table from a broken query.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        q = supabase.table("paper_trades").select("*").eq("status", "open")
        if engine:
            q = q.eq("engine", engine)
        result = q.execute()
        return result.data or []
    except Exception as e:
        raise _table_fault("paper_trades", e)


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4: /api/pnl_summary
# ════════════════════════════════════════════════════════════════════════════
@router.get("/api/pnl_summary", response_model=PnLSummary, tags=["Portfolio"])
async def get_pnl_summary(supabase=Depends(get_supabase)):
    """Aggregated paper PnL statistics across all closed trades.

    Suggest-only product: nothing places an order, so the ledger is empty and every figure below is
    zero. `suggest_only` is in the response so the UI can say "no orders are placed" rather than
    rendering a confident $0.00 that reads as a flat book.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        result = supabase.table("paper_trades").select("*").eq("status", "closed").execute()
        trades = result.data or []

        if not trades:
            return PnLSummary(
                total_paper_trades=0, winning_trades=0, win_rate_pct=0.0,
                total_pnl_cents=0.0, avg_edge_pct=0.0,
                largest_win_cents=0.0, largest_loss_cents=0.0,
                as_of=datetime.now(timezone.utc),
            )

        pnls = [t.get("pnl_cents", 0) for t in trades]
        edges = [t.get("edge_pct", 0) for t in trades]
        wins = [p for p in pnls if p > 0]

        return PnLSummary(
            total_paper_trades=len(trades),
            winning_trades=len(wins),
            win_rate_pct=round(len(wins) / len(trades) * 100, 1),
            total_pnl_cents=round(sum(pnls), 2),
            avg_edge_pct=round(sum(edges) / len(edges), 2) if edges else 0.0,
            largest_win_cents=max(pnls) if pnls else 0.0,
            largest_loss_cents=min(pnls) if pnls else 0.0,
            as_of=datetime.now(timezone.utc),
        )
    except Exception as e:
        raise _table_fault("paper_trades", e)


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 5: /api/nws_weather (removed: the cache-backed scanner endpoint, 2026-10-01)
# ════════════════════════════════════════════════════════════════════════════


# ── Trading HQ: the public Alpaca PAPER portfolio (spec 2026-10-29 §4.2) ─────
# Plain `def`: the Alpaca reads are blocking `requests` calls, so FastAPI runs these in its threadpool.

def _book_or_400(book: str) -> str:
    from tradehub.portfolio.books import BOOKS

    if book not in BOOKS:
        raise HTTPException(400, f"unknown book {book!r} (known: {', '.join(BOOKS)})")
    return book


@router.get("/api/portfolio/books", tags=["Portfolio"])
def get_portfolio_books(supabase=Depends(get_supabase)):
    """One headline per book -- state, equity, return, position count, live ideas -- for the
    Portfolio page's book tabs."""
    from tradehub.portfolio import books as _books
    from tradehub.portfolio import service
    from tradehub.workshop import store as _store

    out = []
    for name in _books.names():
        payload = service.portfolio(supabase, book_name=name)
        score = payload.get("scoreboard") or {}
        try:
            live = [a for a in _store.activations(supabase, name)
                    if a.get("live_at") and not a.get("killed_at")]
        except Exception:  # noqa: BLE001 -- the headline still reads without the count
            live = []
        out.append({"book": name, "label": _books.BOOKS[name]["label"],
                    "detail": _books.BOOKS[name]["detail"],
                    "state": payload.get("state"), "as_of": payload.get("as_of"),
                    "equity": score.get("equity"), "return_pct": score.get("return_pct"),
                    "positions": len(payload.get("positions") or []),
                    "live_ideas": len(live)})
    return {"books": out}


@router.get("/api/portfolio", tags=["Portfolio"])
def get_portfolio(book: str = "main", supabase=Depends(get_supabase)):
    from tradehub.portfolio import service

    name = _book_or_400(book)  # before the try: a bad book is a 400, not a table fault
    try:
        out = service.portfolio(supabase, book_name=name)
        out.pop("account_number", None)  # public page: the number identifies the broker account
        return out
    except Exception as exc:  # noqa: BLE001
        raise _table_fault(service.SNAPSHOTS, exc) from exc


@router.get("/api/kalshi-demo", tags=["Portfolio"])
def get_kalshi_demo(supabase=Depends(get_supabase)):
    """The Kalshi DEMO book behind the Portfolio page's third tab: the live
    demo balance and positions (cached ~15s in kalshi_demo.live_summary)
    plus the demo runner's own record against the shadow record for the
    same decisions. Read-only -- the runner is the only writer, and
    `book=kalshi` never reaches the Alpaca handler above."""
    from tradehub import kalshi_demo
    from tradehub.core.kalshi_portfolio import (
        KalshiPortfolio,
        NotDemoHostError,
        check_portfolio_available,
    )

    if not check_portfolio_available():
        return {"state": "not_connected", "demo": True, "note": kalshi_demo.NOTE}
    try:
        portfolio = KalshiPortfolio()
        # The tab is labelled demo; never serve a live host's balances or
        # positions under that label. The guard runs before any account
        # read (build_report is unreachable unless it passes).
        portfolio.assert_demo_host()
    except (ValueError, NotDemoHostError):
        return {"state": "not_connected", "demo": True, "note": kalshi_demo.NOTE}
    try:
        return kalshi_demo.build_report(
            supabase, portfolio, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        raise _table_fault(kalshi_demo.ORDERS, exc) from exc


@router.get("/api/portfolio/closed", tags=["Portfolio"])
def get_portfolio_closed(book: str = "main", supabase=Depends(get_supabase)):
    from tradehub.portfolio import service

    return service.closed(supabase, book_name=_book_or_400(book))


@router.get("/api/portfolio/activity", tags=["Portfolio"])
def get_portfolio_activity(book: str = "main", supabase=Depends(get_supabase)):
    from tradehub.portfolio import service

    return service.activity(supabase, book_name=_book_or_400(book))


class _OptionLegIn(BaseModel):
    """One leg of a combo, shared by the machine order model and the hand-order
    form model (2026-11-09): an OCC symbol, a side, an absolute contract count,
    and an optional open/close intent (defaulted by side in validation)."""

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(min_length=1, max_length=21)
    side: str
    qty: int = Field(ge=1, le=100_000)
    position_intent: str | None = None


class _OrderIn(BaseModel):
    # Symbol/qty/side are optional at the schema since 2026-11-09: a combo body
    # carries legs[] instead, and the route refuses whichever shape is
    # incomplete. Symbol is 21 wide for OCC contracts; limit_price carries no
    # gt=0 because a combo's net limit is negative for a credit -- the route
    # enforces the sign per shape.
    symbol: str | None = Field(default=None, max_length=21)
    qty: int | None = Field(default=None, ge=1, le=100_000)
    side: str | None = None
    order_type: str = "market"
    limit_price: float | None = None
    time_in_force: str = "day"
    idea_id: int | None = None
    book: str = "main"
    position_intent: str | None = None
    legs: list[_OptionLegIn] | None = None


def _place_form_option_order(body: _OrderIn, user: dict):
    """The hand-order form's options path (2026-11-09): the SAME validation the
    machine API runs -- the shared tradehub.portfolio.option_orders checks
    (contract exists/tradable, defined-risk, max loss vs options buying power)
    -- then the same paper_orders submission. The doors' own fences differ (an
    admin session instead of a key, no per-key caps, the manual-/idea-
    client_order_id family instead of ext-); the rules for what may be placed
    do not, so the two surfaces cannot diverge."""
    from uuid import uuid4

    from tradehub.portfolio import option_orders, paper_orders
    from tradehub.portfolio.alpaca_paper import AccountNotConnected
    from tradehub.portfolio.options import fetch_mid

    book = body.book
    try:
        if body.legs:
            legs = option_orders.normalize_legs([leg.model_dump() for leg in body.legs])
            kind = "combo"
        else:
            legs = [option_orders.normalize_leg(
                {"symbol": body.symbol, "side": body.side, "qty": body.qty,
                 "position_intent": body.position_intent})]
            kind = "single"
    except option_orders.OptionOrderError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.time_in_force != "day":
        raise HTTPException(status_code=422, detail=(
            f"option orders are day orders: Alpaca paper does not take {body.time_in_force} "
            "on an option order, and the form will not silently downgrade it to day"))
    if kind == "combo":
        if body.order_type != "limit" or body.limit_price is None or body.limit_price == 0:
            raise HTTPException(status_code=422, detail=(
                "a combo is placed at one net limit_price "
                "(positive is a debit paid, negative a credit taken)"))
        parent, ratios = option_orders.parent_and_ratios(legs)
        premium = float(body.limit_price) * parent * 100
    else:
        if body.order_type not in ("market", "limit"):
            raise HTTPException(status_code=422, detail="hand-placed option orders are market or limit only")
        if body.order_type == "limit" and body.limit_price is None:
            raise HTTPException(status_code=422, detail="a limit order needs a limit_price")
        if body.limit_price is not None and body.limit_price <= 0:
            raise HTTPException(status_code=422, detail="a single-leg limit_price must be positive")
        parent, ratios = legs[0]["qty"], [1]
        only = legs[0]
        if only["position_intent"] in option_orders.OPEN_INTENTS:
            if body.order_type == "limit":
                price = float(body.limit_price)
            else:
                price = fetch_mid(only["symbol"], book=book)
                if price is None:
                    raise HTTPException(status_code=424, detail=(
                        f"no usable quote for {only['symbol']}; the order cannot be priced"))
            premium = option_orders.opening_premium(legs, {only["symbol"]: price})
        else:
            premium = 0.0
    for symbol in dict.fromkeys(leg["symbol"] for leg in legs):
        try:
            row = option_orders.contract(symbol, book)
        except AccountNotConnected as exc:
            raise HTTPException(status_code=424, detail="the paper account is not connected") from exc
        except Exception as exc:  # noqa: BLE001 -- unverifiable is unplaceable: fail closed
            raise HTTPException(status_code=424, detail=f"the contract for {symbol} could not be verified") from exc
        if row is None:
            raise HTTPException(status_code=422, detail=(
                f"{symbol} is not a tradable option contract on this paper account"))
    try:
        held = option_orders.positions_map(book)
    except AccountNotConnected as exc:
        raise HTTPException(status_code=424, detail="the paper account is not connected") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=424, detail=(
            "positions could not be read; the defined-risk check cannot run")) from exc
    reason = option_orders.check_defined_risk(legs, held)
    if reason is not None:
        raise HTTPException(status_code=422, detail=reason)
    max_loss = option_orders.max_loss(legs, held, premium)
    if any(leg["position_intent"] in option_orders.OPEN_INTENTS for leg in legs):
        try:
            obp = option_orders.options_buying_power(book)
        except AccountNotConnected as exc:
            raise HTTPException(status_code=424, detail="the paper account is not connected") from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=424, detail=(
                "buying power could not be read; the max-loss check cannot run")) from exc
        if obp is None or max_loss > obp:
            raise HTTPException(status_code=422, detail=(
                f"max loss ${max_loss:,.0f} exceeds the book's options buying power ${obp:,.0f}"
                if obp is not None else "the account reports no options buying power"))
    tag = f"idea-{body.idea_id}-manual-" if body.idea_id is not None else "manual-"
    client_order_id = tag + uuid4().hex[:12]
    try:
        if kind == "single":
            leg = legs[0]
            order = paper_orders.submit(
                leg["symbol"], leg["qty"], leg["side"], client_order_id,
                order_type=body.order_type, time_in_force="day",
                limit_price=body.limit_price if body.order_type == "limit" else None,
                book=book, position_intent=leg["position_intent"])
        else:
            mleg_legs = [{"symbol": leg["symbol"], "side": leg["side"], "ratio_qty": ratio,
                          "position_intent": leg["position_intent"]}
                         for leg, ratio in zip(legs, ratios)]
            order = paper_orders.submit_mleg(mleg_legs, parent, float(body.limit_price),
                                             client_order_id, book=book)
    except paper_orders.OrdersDisabled as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except paper_orders.DuplicateOrder as exc:
        raise HTTPException(status_code=409, detail="an order with this client_order_id was already sent") from exc
    except AccountNotConnected as exc:
        raise HTTPException(status_code=424, detail="the paper account is not connected") from exc
    except (paper_orders.OrderRejected, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response = {"order": order, "client_order_id": client_order_id, "placed_by": user["email"]}
    if kind == "single":
        response["position_intent"] = legs[0]["position_intent"]
    else:
        response["option"] = {
            "legs": [{"symbol": leg["symbol"], "side": leg["side"], "qty": leg["qty"],
                      "ratio_qty": ratio, "position_intent": leg["position_intent"]}
                     for leg, ratio in zip(legs, ratios)],
            "parent_qty": parent, "net_limit_price": float(body.limit_price),
            "net_price_convention": option_orders.NET_PRICE_CONVENTION, "max_loss": max_loss}
    return response


@router.post("/api/portfolio/orders", tags=["Portfolio"])
def place_portfolio_order(body: _OrderIn, user: dict = Depends(admin.require_admin)):
    """Place one paper order by hand (Kevin, signed in). This is the critique's signed-in order
    endpoint -- deliberately NOT a machine API: the only credential is Kevin's admin session,
    and the only order path is paper_orders.submit, so the paper host, the TRADEHUB_PAPER_ORDERS
    switch and the protective-order tag rules all still apply. Plain market/limit only; stops
    and GTC orders remain the hub's own protective orders, never hand-placed.
    With an idea_id the client_order_id carries the `idea-<n>-` tag, so the order shows in that
    idea's order log and fills like an auto order does.
    Option orders (2026-11-09) -- a single-leg OCC symbol, or legs[] for a combo --
    take the _place_form_option_order path: the machine API's shared validation,
    so a naked short is refused here exactly as it is there."""
    from uuid import uuid4

    from tradehub.portfolio import option_orders, paper_orders
    from tradehub.portfolio.alpaca_paper import AccountNotConnected
    from tradehub.workshop.spec import TICKER

    _book_or_400(body.book)
    if body.legs or option_orders.is_option_symbol(body.symbol):
        return _place_form_option_order(body, user)
    symbol = (body.symbol or "").strip().upper()
    if not TICKER.match(symbol):
        raise HTTPException(status_code=422, detail=f"not a ticker: {body.symbol!r}")
    if body.side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="side must be buy or sell")
    if body.qty is None or body.qty < 1:
        raise HTTPException(status_code=422, detail="qty must be at least 1")
    if body.order_type not in ("market", "limit"):
        raise HTTPException(status_code=422, detail="hand-placed orders are market or limit only")
    if body.time_in_force not in ("opg", "cls", "day"):
        raise HTTPException(status_code=422, detail="time_in_force must be opg, cls or day")
    if body.order_type == "limit" and body.limit_price is None:
        raise HTTPException(status_code=422, detail="a limit order needs a limit_price")
    if body.limit_price is not None and body.limit_price <= 0:
        raise HTTPException(status_code=422, detail="limit_price must be positive")
    tag = f"idea-{body.idea_id}-manual-" if body.idea_id is not None else "manual-"
    client_order_id = tag + uuid4().hex[:12]
    try:
        order = paper_orders.submit(symbol, body.qty, body.side, client_order_id,
                                    order_type=body.order_type, time_in_force=body.time_in_force,
                                    limit_price=body.limit_price if body.order_type == "limit" else None,
                                    book=body.book)
    except paper_orders.OrdersDisabled as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except paper_orders.DuplicateOrder as exc:
        raise HTTPException(status_code=409, detail="an order with this client_order_id was already sent") from exc
    except AccountNotConnected as exc:
        raise HTTPException(status_code=424, detail="the paper account is not connected") from exc
    except (paper_orders.OrderRejected, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"order": order, "client_order_id": client_order_id, "placed_by": user["email"]}


@router.get("/api/portfolio/manual-actions", tags=["Portfolio"])
def get_manual_actions(book: str = "main", user: dict = Depends(admin.require_admin),
                       supabase=Depends(get_supabase)):
    """The auto-trader's hand-off list for one book (Kevin, 2026-11-02): option legs it
    would not price or size alone. Signed-in only -- the detail is strategy-shaped."""
    rows = workshop_store.manual_actions(supabase, _book_or_400(book))
    ideas = {i["id"]: i.get("title") for i in supabase.table("ideas").select("id, title").execute().data or []}
    return {"book": book, "actions": [{**r, "idea_title": ideas.get(r.get("idea_id"))} for r in rows]}


@router.get("/api/portfolio/portfolio-check", tags=["Portfolio"])
def get_portfolio_check(book: str = "main", user: dict = Depends(admin.require_admin),
                        supabase=Depends(get_supabase)):
    """The Portfolio card's payload (Kevin, 2026-11-09): thesis weights against
    the caps and targets, the three cluster exposures, cash %, and the most
    recent check outcomes -- all from tradehub.portfolio.portfolio_check, the
    same engine (and the same stored targets and series) the preflight gate and
    the activation gate read, so the card and the gates can never disagree."""
    from tradehub.portfolio import portfolio_check

    try:
        return portfolio_check.current_state(supabase, _book_or_400(book))
    except Exception as exc:  # noqa: BLE001 -- an unreadable book is stated, not faked
        raise HTTPException(status_code=503,
                            detail=f"the {book} book could not be read ({type(exc).__name__})") from exc


@router.post("/api/portfolio/manual-actions/{action_id}/resolve", tags=["Portfolio"])
def resolve_manual_action(action_id: int, body: dict, user: dict = Depends(admin.require_admin),
                          supabase=Depends(get_supabase)):
    state = str(body.get("state") or "")
    if state not in ("done", "dismissed"):
        raise HTTPException(status_code=422, detail="state must be done or dismissed")
    workshop_store.resolve_manual_action(supabase, action_id, state)
    return {"resolved": action_id, "state": state}


@router.get("/api/portfolio/open-orders", tags=["Portfolio"])
def get_portfolio_open_orders(book: str = "main", user: dict = Depends(admin.require_admin)):
    """Every order resting on the paper account, for the Portfolio page's staged-orders
    panel: the same broker-wide view the machine API exposes at /api/v1/orders/open."""
    from tradehub.api.machine_api import open_broker_orders
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    try:
        return {"orders": open_broker_orders(_book_or_400(book))}
    except AccountNotConnected as exc:
        raise HTTPException(status_code=424, detail="the paper account is not connected") from exc
