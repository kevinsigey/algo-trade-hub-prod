"""Machine API routes — split from tradehub/api/main.py in step 20
(code health: main.py had grown past 5,000 lines). Handlers moved verbatim;
the app in main.py includes this router, so every path is unchanged.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from tradehub.api.dependencies import get_supabase



log = logging.getLogger(__name__)

from tradehub.api.routers.portfolio import _OptionLegIn
router = APIRouter()


# ── Machine API (phase-2 spec §1, step 2): key-authenticated, paper-only, shipped OFF. ────
# POST /api/v1/orders places through the same paper_orders.submit as the form above, under
# three extra fences the form does not need: the TRADEHUB_MACHINE_ORDERS kill switch, the
# per-key caps stored on the key, and a caller-supplied client_order_id the server namespaces
# to ext-<key_id>-<caller> so a retry can never double-place and a machine can never mint an
# idea-/manual-/protective id. Market orders shipped in v1 (step 2); limit orders in v1.1
# (step 5), their notional priced at the limit. Protective stops joined 2026-11-02 (Kevin's
# staged mirror book had no way to rest its stops): order_type "stop" + stop_price + gtc is
# the one protective shape the door takes, fenced to shares actually held (stop_capacity),
# namespaced to the ext-<key>-stop- tag family paper_orders sanctions, and priced for the
# notional cap at the stop. order_class and trailing stops still 422 here. GTC share limits
# joined 2026-11-10 (Kevin: resting exits must not expire daily): a limit order with
# time_in_force "gtc" is the second resting shape, namespaced to the ext-<key>-gtc- tag
# family; GTC market orders and GTC splits still 422 in validate_order. GTC option limits
# joined later the same day (Kevin, after the probe proved Alpaca paper takes GTC on
# single-leg and mleg options): a limit option order with time_in_force "gtc" rides the
# same ext-<key>-gtc- family, placed through submit/submit_mleg carrying the tif; GTC
# market option orders and opg/cls on options still 422 in validate_order.
# Extended-hours equity limits joined 2026-11-17 (Kevin via the trading chat:
# exits into after-hours news and pre-market entries): extended_hours=true
# passes through to Alpaca on limit orders with time_in_force day or gtc --
# a gtc one rides the ext-<key>-gtc- family above, which is the sanction
# paper_orders requires for a resting limit; market orders, opg/cls,
# options and splits with the flag still 422 in validate_order.
class _MachineOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # order_class and other broker shapes 422 here

    # Symbol is 21 chars wide since 2026-11-09: an OCC contract symbol
    # (SPY261113P00570000) is a first-class order here, not a too-long ticker.
    # Symbol/qty/side are optional at the schema because a combo body carries
    # legs[] instead; validate_order refuses whichever shape is incomplete.
    symbol: str | None = Field(default=None, max_length=21)
    qty: int | None = Field(default=None, ge=1, le=100_000)
    side: str | None = None
    client_order_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    order_type: str = "market"
    time_in_force: str = "day"
    # No gt=0: a combo's net limit is negative for a credit. validate_order
    # enforces the sign per shape (single-leg limits stay positive).
    limit_price: float | None = None
    stop_price: float | None = Field(default=None, gt=0)
    idea_id: int | None = None
    # Attribution (2026-11-11): an order with no idea_id must state why it
    # exists. validate_order refuses a placement that carries neither, and the
    # reason is stored on the order's label row so Portfolio results can split
    # tested ideas from discretionary trades with their reasons attached.
    reason: str | None = Field(default=None, max_length=200)
    # Single-leg options (2026-11-09): the open/close intent Alpaca needs.
    position_intent: str | None = None
    # Combos (2026-11-09): legs[] + ONE net limit_price, placed as one mleg order.
    legs: list[_OptionLegIn] | None = None
    # A parent order (2026-11-08): qty is the TOTAL and the server chunks it under
    # the key's caps, placing children <caller id>-1..n as one logical order.
    split: bool = False
    # Extended hours (2026-11-17): passed through to Alpaca on equity
    # limit orders (time_in_force day or gtc) so the order can fill in
    # the pre-market, after-hours and overnight sessions. validate_order
    # fences the shapes (no market orders, no opg/cls, no options, no
    # splits); the service layer's own fence agrees.
    extended_hours: bool = False
    # A thesis tag (2026-11-08): a short slug stored with the order's label and
    # surfaced on the resulting portfolio lots. Metadata only -- it never affects
    # caps, routing or the ext- namespacing.
    tag: str | None = Field(default=None, max_length=24, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    # A caller's exit CLAIM (2026-11-09): recorded and reported, never trusted.
    # The exit classification that exempts an order from the machine caps is
    # book math computed in machine_api.validate_order; when the claim and the
    # math disagree, the math wins and the preflight says so.
    exit: bool | None = None
    # Thesis tracker linkage (tracker design PR 5): carrying a play_kind
    # makes this an event-lab order — the tracker preflight blocks engage
    # (opposing case, modal value, the governing unit, the cash floor)
    # and a trade_links row is written at placement. shadow=true records
    # the link WITHOUT placing (play kind c's graded form); top_tier
    # selects the Schedule v2 top unit; risk_amount is the research
    # file's sized risk for a share play (options always use their
    # computed max loss); stop_loss_price lets a share play's
    # risk-to-stop be computed instead of falling back to notional.
    play_kind: str | None = Field(default=None, pattern=r"^[abc]$")
    thesis_id: int | None = None
    forecast_id: int | None = None
    modal_value: float | None = None
    opposing_case_ref: str | None = Field(default=None, max_length=500)
    shadow: bool = False
    top_tier: bool = False
    risk_amount: float | None = Field(default=None, ge=0)
    stop_loss_price: float | None = Field(default=None, gt=0)


@router.post("/api/v1/orders", tags=["Machine API"])
def place_machine_order(body: _MachineOrderIn, authorization: str | None = Header(None),
                        supabase=Depends(get_supabase)):
    from fastapi.responses import JSONResponse

    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio import paper_orders
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    route = "POST /api/v1/orders"

    def refused(outcome: str, status: int, detail: str):
        machine_keys.record_event(supabase, key["id"], route, f"refused:{outcome}",
                                  detail=detail, client_order_id=body.client_order_id)
        raise HTTPException(status_code=status, detail=detail)

    machine_api.require_scope(supabase, key, "orders:place", route)
    # Per-book keys (Kevin, 2026-11-03): the order lands on the KEY's book, never a
    # caller-chosen one -- _MachineOrderIn does not even carry a book field. Every
    # fence below is machine_api.validate_order, the one validation path the
    # preflight route shares (2026-11-08), so the two can never drift.
    spec = {"symbol": body.symbol, "qty": body.qty, "side": body.side,
            "order_type": body.order_type, "time_in_force": body.time_in_force,
            "limit_price": body.limit_price, "stop_price": body.stop_price,
            "split": body.split, "extended_hours": body.extended_hours,
            "position_intent": body.position_intent, "exit_claim": body.exit,
            "legs": [leg.model_dump() for leg in body.legs] if body.legs else None,
            "tag": body.tag, "idea_id": body.idea_id, "reason": body.reason,
            "play_kind": body.play_kind, "thesis_id": body.thesis_id,
            "forecast_id": body.forecast_id, "modal_value": body.modal_value,
            "opposing_case_ref": body.opposing_case_ref, "shadow": body.shadow,
            "top_tier": body.top_tier, "risk_amount": body.risk_amount,
            "stop_loss_price": body.stop_loss_price}
    result = machine_api.validate_order(supabase, key, spec)
    if result["refusal"] is not None:
        refused(*result["refusal"])
    book, symbol = result["book"], result["symbol"]
    # Thesis tracker (design PR 5): a shadow record writes its link and
    # returns without touching the broker — graded, never placed. A
    # placed tracker order writes its link beside the placement, one
    # per client_order_id (one per split child); a failed link write is
    # reported on the response, never allowed to un-place the order —
    # the label() precedent directly above.
    tracker = result["tracker"]

    def write_link(client_order_id: str) -> str | None:
        if tracker is None:
            return None
        try:
            from tradehub.tracker import links as tracker_links

            tracker_links.record_link(
                supabase, client_order_id=client_order_id, book=book,
                play_kind=tracker["play_kind"],
                modal_value=tracker["modal_value"],
                opposing_case_ref=tracker["opposing_case_ref"],
                forecast_id=tracker["forecast_id"],
                thesis_id=tracker["thesis_id"],
                shadow=tracker["shadow"])
        except Exception:  # noqa: BLE001 -- the order exists; the link must not un-place it
            return "tracker link failed"
        return None

    if tracker is not None and tracker["shadow"]:
        client_order_id = f"ext-{key['id']}-{body.client_order_id}"
        note = write_link(client_order_id)
        if note:
            # A shadow request's ONLY effect is its link: reporting
            # success with nothing recorded would lose the record
            # silently. record_link is idempotent, so a retry is safe.
            refused("tracker_link", 503,
                    "the shadow record could not be written; "
                    "retry the request")
        machine_keys.record_event(supabase, key["id"], route, "shadow_recorded",
                                  detail=note, client_order_id=client_order_id)
        return {"shadow": True, "client_order_id": client_order_id,
                "placed_by": f"api:{key['label']}", "tag": body.tag,
                "idea_id": body.idea_id, "reason": body.reason,
                "exit": result["exit"],
                "portfolio_check": result["portfolio_check"],
                "tracker": tracker, "link_note": note}
    submit_kwargs = {}
    if body.order_type == "stop":
        submit_kwargs["stop_price"] = body.stop_price

    def submit_one(qty: int, client_order_id: str):
        # extended_hours joins the call ONLY when set -- an order without
        # the flag reaches submit exactly as it did before (the position
        # intent precedent in paper_orders).
        return paper_orders.submit(symbol, qty, body.side, client_order_id,
                                   order_type=body.order_type, time_in_force=body.time_in_force,
                                   limit_price=body.limit_price if body.order_type == "limit" else None,
                                   **({"extended_hours": True} if body.extended_hours else {}),
                                   book=book, **submit_kwargs)

    def label(order_id: str) -> str | None:
        try:
            from tradehub.workshop import store as workshop_store

            workshop_store.add_label(supabase, order_id, body.idea_id, f"api:{key['label']}",
                                     tag=body.tag, reason=body.reason)
        except Exception:  # noqa: BLE001 -- the order exists; a failed label must not un-place it
            return "label failed"
        return None

    if result["option"] is not None:
        # Options placement (2026-11-09): ONE order -- a single leg through
        # paper_orders.submit carrying its position intent, or the whole combo
        # as one mleg order through submit_mleg, never sequential legs.
        # Namespacing, idempotency, labelling and the audit event are exactly
        # the share path's; every cap already ran in validate_order.
        option = result["option"]
        if option["time_in_force"] == "gtc":  # validate_order has fenced this to limit orders
            client_order_id = f"ext-{key['id']}-gtc-{body.client_order_id}"
        else:
            client_order_id = f"ext-{key['id']}-{body.client_order_id}"
        try:
            if option["kind"] == "single":
                leg = option["legs"][0]
                order = paper_orders.submit(
                    leg["symbol"], leg["qty"], leg["side"], client_order_id,
                    order_type=option["order_type"], time_in_force=option["time_in_force"],
                    limit_price=body.limit_price if option["order_type"] == "limit" else None,
                    book=book, position_intent=leg["position_intent"])
            else:
                mleg_legs = [{"symbol": leg["symbol"], "side": leg["side"],
                              "ratio_qty": ratio, "position_intent": leg["position_intent"]}
                             for leg, ratio in zip(option["legs"], option["ratios"])]
                order = paper_orders.submit_mleg(mleg_legs, option["parent_qty"],
                                                 option["net_limit_price"], client_order_id,
                                                 book=book, time_in_force=option["time_in_force"])
        except paper_orders.OrdersDisabled as exc:
            refused("paper_switch_off", 409, str(exc))
        except paper_orders.DuplicateOrder:
            write_link(client_order_id)  # a retry repairs a link the
            # first attempt failed to write (idempotent)
            refused("duplicate", 409, "an order with this client_order_id was already sent")
        except AccountNotConnected:
            refused("account", 424, "the paper account is not connected")
        except (paper_orders.OrderRejected, ValueError) as exc:
            refused("rejected", 422, str(exc))
        machine_keys.record_event(supabase, key["id"], route, "placed",
                                  detail=machine_api.exit_event_detail(
                                      label(order["id"]), result["exit"]["is_exit"]),
                                  client_order_id=client_order_id)
        link_note = write_link(client_order_id)
        if link_note:
            machine_keys.record_event(
                supabase, key["id"], route, "tracker_link_failed",
                detail=link_note, client_order_id=client_order_id)
        from datetime import datetime, timezone

        session = machine_api.session_fields(
            {**order, "time_in_force": option["time_in_force"],
             "submitted_at": order.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
             "status": order.get("status", "accepted")})
        response = {"order": order, "client_order_id": client_order_id,
                    "placed_by": f"api:{key['label']}", "tag": body.tag,
                    "idea_id": body.idea_id, "reason": body.reason,
                    "exit": result["exit"], **session,
                    "portfolio_check": result["portfolio_check"],
                    "tracker": tracker, "link_note": link_note}
        if option["kind"] == "single":
            response["position_intent"] = option["legs"][0]["position_intent"]
        else:
            from tradehub.portfolio import option_orders as _option_orders

            response.update({
                "legs": [{"symbol": leg["symbol"], "side": leg["side"], "qty": leg["qty"],
                          "ratio_qty": ratio, "position_intent": leg["position_intent"]}
                         for leg, ratio in zip(option["legs"], option["ratios"])],
                "parent_qty": option["parent_qty"],
                "net_limit_price": option["net_limit_price"],
                "net_price_convention": _option_orders.NET_PRICE_CONVENTION,
                "max_loss": option["max_loss"]})
        return response

    if not body.split:
        if body.order_type == "stop":
            client_order_id = f"ext-{key['id']}-stop-{body.client_order_id}"
        elif body.time_in_force == "gtc":  # validate_order has fenced this to limit orders
            client_order_id = f"ext-{key['id']}-gtc-{body.client_order_id}"
        else:
            client_order_id = f"ext-{key['id']}-{body.client_order_id}"
        try:
            order = submit_one(body.qty, client_order_id)
        except paper_orders.OrdersDisabled as exc:
            refused("paper_switch_off", 409, str(exc))
        except paper_orders.DuplicateOrder:
            write_link(client_order_id)  # a retry repairs a link the
            # first attempt failed to write (idempotent)
            refused("duplicate", 409, "an order with this client_order_id was already sent")
        except AccountNotConnected:
            refused("account", 424, "the paper account is not connected")
        except (paper_orders.OrderRejected, ValueError) as exc:
            refused("rejected", 422, str(exc))
        machine_keys.record_event(supabase, key["id"], route, "placed",
                                  detail=machine_api.exit_event_detail(
                                      label(order["id"]), result["exit"]["is_exit"]),
                                  client_order_id=client_order_id)
        link_note = write_link(client_order_id)
        if link_note:
            machine_keys.record_event(
                supabase, key["id"], route, "tracker_link_failed",
                detail=link_note, client_order_id=client_order_id)
        from datetime import datetime, timezone

        session = machine_api.session_fields(
            {**order, "time_in_force": body.time_in_force,
             "submitted_at": order.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
             "status": order.get("status", "accepted")})
        return {"order": order, "client_order_id": client_order_id,
                "placed_by": f"api:{key['label']}", "tag": body.tag,
                "idea_id": body.idea_id, "reason": body.reason,
                "exit": result["exit"], **session,
                "portfolio_check": result["portfolio_check"],
                "tracker": tracker, "link_note": link_note}

    # A parent order: the server chunks the total under the key's caps and places
    # the children as one logical order. A child the broker already has (a retry of
    # the same group) counts as placed -- the group is idempotent, never doubled.
    # A child that fails midway stops the split and is REPORTED with the children
    # that did place: a partial split is a state the caller must see, not an error
    # that pretends nothing happened.
    namespaced = f"ext-{key['id']}-{body.client_order_id}"
    placed_children: list[str] = []
    failure: tuple[str, int, str, str] | None = None  # outcome, status, detail, child id
    for i, chunk in enumerate(result["chunks"], 1):
        child_id = f"{namespaced}-{i}"
        try:
            order = submit_one(chunk, child_id)
        except paper_orders.DuplicateOrder:
            write_link(child_id)  # idempotent: the retry keeps its link
            placed_children.append(child_id)
            continue
        except paper_orders.OrdersDisabled as exc:
            failure = ("paper_switch_off", 409, str(exc), child_id)
            break
        except AccountNotConnected:
            failure = ("account", 424, "the paper account is not connected", child_id)
            break
        except (paper_orders.OrderRejected, ValueError) as exc:
            failure = ("rejected", 422, str(exc), child_id)
            break
        note = label(order["id"])
        link_note = write_link(child_id)
        detail = f"group:{body.client_order_id}" + (f"; {note}" if note else "")
        detail += f"; {link_note}" if link_note else ""
        detail = machine_api.exit_event_detail(detail, result["exit"]["is_exit"])
        machine_keys.record_event(supabase, key["id"], route, "placed",
                                  detail=detail, client_order_id=child_id)
        placed_children.append(child_id)
    if failure is not None:
        outcome, status, detail, child_id = failure
        if not placed_children:
            refused(outcome, status, detail)
        machine_keys.record_event(supabase, key["id"], route, f"refused:{outcome}",
                                  detail=f"split child {child_id}: {detail}",
                                  client_order_id=child_id)
        return JSONResponse(status_code=status, content={
            "detail": f"split stopped at {child_id}: {detail}",
            "group_id": body.client_order_id, "client_order_id": namespaced,
            "placed_children": placed_children,
            "failed_child": {"client_order_id": child_id, "detail": detail}})
    try:
        broker = machine_api.broker_orders(book=book)
    except AccountNotConnected:
        broker = {}
    events = machine_api.group_events(supabase, key["id"], namespaced, body.client_order_id)
    # A child the broker window has not caught up with still reads with the quantity
    # this call placed -- the group's total never depends on the read window.
    chunks = {f"{namespaced}-{i}": c for i, c in enumerate(result["chunks"], 1)}
    for event in events:
        cid = event["client_order_id"]
        if cid not in broker and cid in chunks:
            broker[cid] = {"client_order_id": cid, "symbol": symbol, "side": body.side,
                           "type": body.order_type, "time_in_force": body.time_in_force,
                           "qty": str(chunks[cid]), "filled_qty": "0", "status": "accepted",
                           "submitted_at": event["at"]}
    return {"group": _machine_group_view(body.client_order_id, namespaced, events, broker,
                                         _machine_label_tags(supabase)),
            "client_order_id": namespaced, "placed_by": f"api:{key['label']}", "tag": body.tag,
            "idea_id": body.idea_id, "reason": body.reason,
            "exit": result["exit"], "portfolio_check": result["portfolio_check"],
            "tracker": tracker}


@router.post("/api/v1/orders/preflight", tags=["Machine API"])
def preflight_machine_order(body: _MachineOrderIn, authorization: str | None = Header(None),
                            supabase=Depends(get_supabase)):
    """The placement validators without the placement (2026-11-08): what the real call
    would do, stated before it does it -- per-gate pass/fail, cap headroom, the book's
    switch and breaker state, and the account facts a hand-split trim used to need
    memory for (buying power, shares actually held across lots, shortability for a
    sell that would open a short). Shares its one validation path with
    POST /api/v1/orders (machine_api.validate_order). Audited as `preflight`, never
    `placed`: the daily cap counts placements, and a question is not one."""
    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio import alpaca_paper, breakers

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    route = "POST /api/v1/orders/preflight"
    machine_api.require_scope(supabase, key, "orders:place", route)
    spec = {"symbol": body.symbol, "qty": body.qty, "side": body.side,
            "order_type": body.order_type, "time_in_force": body.time_in_force,
            "limit_price": body.limit_price, "stop_price": body.stop_price,
            "split": body.split, "extended_hours": body.extended_hours,
            "position_intent": body.position_intent, "exit_claim": body.exit,
            "legs": [leg.model_dump() for leg in body.legs] if body.legs else None,
            "tag": body.tag, "idea_id": body.idea_id, "reason": body.reason,
            "play_kind": body.play_kind, "thesis_id": body.thesis_id,
            "forecast_id": body.forecast_id, "modal_value": body.modal_value,
            "opposing_case_ref": body.opposing_case_ref, "shadow": body.shadow,
            "top_tier": body.top_tier, "risk_amount": body.risk_amount,
            "stop_loss_price": body.stop_loss_price}
    result = machine_api.validate_order(supabase, key, spec, dry_run=True)
    from tradehub.portfolio import option_orders as _option_orders

    if body.legs or _option_orders.is_option_symbol(body.symbol):
        # The options preflight (2026-11-09): the same checks validate_order ran
        # (contract, defined-risk, per-leg caps, max loss vs options buying
        # power), the cap headroom with the combo counting once, and the plan --
        # one namespaced order, parent qty for a combo.
        option = result["option"]
        used = result["daily_used"] or 0
        plan = ([{"qty": option["parent_qty"],
                  "client_order_id": (f"ext-{key['id']}-gtc-{body.client_order_id}"
                                      if body.time_in_force == "gtc"
                                      else f"ext-{key['id']}-{body.client_order_id}")}]
                if result["refusal"] is None and option is not None else [])
        machine_keys.record_event(supabase, key["id"], route, "preflight",
                                  detail="ok" if result["refusal"] is None else result["refusal"][0],
                                  client_order_id=body.client_order_id)
        breaker = result["breaker"]
        return {"ok": result["refusal"] is None,
                "kind": "option_combo" if body.legs else "option_single",
                "symbol": result["symbol"], "checks": result["checks"],
                "exit": result["exit"],
                "headroom": {"max_qty_per_order": int(key["max_qty"]),
                             "max_notional_per_order": float(key["max_notional"]),
                             "daily_used": used, "daily_cap": int(key["daily_cap"]),
                             "daily_remaining": int(key["daily_cap"]) - used
                             - (0 if result["exit"]["is_exit"] else len(plan)),
                             "max_loss": option["max_loss"] if option else None,
                             "options_buying_power":
                                 option["options_buying_power"] if option else None},
                "kill_switch": {"machine_orders": machine_api.machine_orders_enabled(),
                                "breaker_tripped": bool(breaker and breaker["tripped"]),
                                "breaker_reasons": (breaker or {}).get("reasons", [])},
                "portfolio_check": result["portfolio_check"],
                "account": {"options_buying_power":
                            option["options_buying_power"] if option else None},
                "option": ({"kind": option["kind"],
                            "legs": [{"symbol": leg["symbol"], "side": leg["side"],
                                      "qty": leg["qty"], "ratio_qty": ratio,
                                      "position_intent": leg["position_intent"]}
                                     for leg, ratio in zip(option["legs"], option["ratios"])],
                            "parent_qty": option["parent_qty"],
                            "net_limit_price": option["net_limit_price"],
                            "net_price_convention": _option_orders.NET_PRICE_CONVENTION,
                            "time_in_force": option["time_in_force"],
                            "max_loss": option["max_loss"]} if option else None),
                "plan": {"children": plan}}
    book, symbol, price = result["book"], result["symbol"], result["price"]
    checks = list(result["checks"])
    account: dict = {"buying_power": None, "held_qty": None, "shortable": None}
    try:
        acct = alpaca_paper.paper_get("/v2/account", book=book) or {}
        if acct.get("buying_power") is not None:
            account["buying_power"] = float(acct["buying_power"])
    except Exception:  # noqa: BLE001 -- an unreadable fact reads as unknown, never as zero
        pass
    if result["refusal"] is None or result["refusal"][0] not in ("book", "symbol", "side"):
        try:
            account["held_qty"] = machine_api.position_qty(symbol, book=book)
        except Exception:  # noqa: BLE001
            pass
    if price is not None and account["buying_power"] is not None:
        notional = price * body.qty
        checks.append({"name": "buying_power", "blocking": False,
                       "ok": body.side != "buy" or notional <= account["buying_power"],
                       "detail": f"buying power ${account['buying_power']:,.0f}"
                                 + (f" against a ${notional:,.0f} order" if body.side == "buy" else "")})
    if body.side == "sell" and account["held_qty"] is not None:
        held = account["held_qty"]
        checks.append({"name": "held_qty", "blocking": False, "ok": body.qty <= held,
                       "detail": f"{held:g} shares held in {symbol} across lots; this sell is for {body.qty}"})
        if body.qty > held:  # the sell opens a short: is the name shortable at all?
            try:
                account["shortable"] = bool(alpaca_paper.asset_flags(symbol, book=book).get("shortable"))
            except Exception:  # noqa: BLE001
                pass
            checks.append({"name": "shortable", "blocking": False, "ok": bool(account["shortable"]),
                           "detail": f"{symbol} is shortable" if account["shortable"]
                                     else f"{symbol} is not flagged shortable"})
    breaker = result["breaker"]
    if breaker is None:
        try:
            breaker = breakers.check(supabase, book)
        except Exception:  # noqa: BLE001
            breaker = None
    namespaced = (f"ext-{key['id']}-stop-{body.client_order_id}" if body.order_type == "stop"
                  else f"ext-{key['id']}-gtc-{body.client_order_id}" if body.time_in_force == "gtc"
                  else f"ext-{key['id']}-{body.client_order_id}")
    if body.split:
        plan = [{"qty": c, "client_order_id": f"{namespaced}-{i}"}
                for i, c in enumerate(result["chunks"], 1)]
    else:
        plan = [{"qty": body.qty, "client_order_id": namespaced}] if result["chunks"] else []
    used = result["daily_used"] or 0
    machine_keys.record_event(supabase, key["id"], route, "preflight",
                              detail="ok" if result["refusal"] is None else result["refusal"][0],
                              client_order_id=body.client_order_id)
    return {"ok": result["refusal"] is None, "symbol": symbol, "side": body.side,
            "qty": body.qty, "split": body.split, "checks": checks, "exit": result["exit"],
            "headroom": {"price_used": price,
                         "order_notional": price * body.qty if price is not None else None,
                         "max_qty_per_order": int(key["max_qty"]),
                         "max_notional_per_order": float(key["max_notional"]),
                         "daily_used": used, "daily_cap": int(key["daily_cap"]),
                         "daily_remaining": int(key["daily_cap"]) - used
                         - (0 if result["exit"]["is_exit"] else len(plan))},
            "kill_switch": {"machine_orders": machine_api.machine_orders_enabled(),
                            "breaker_tripped": bool(breaker and breaker["tripped"]),
                            "breaker_reasons": (breaker or {}).get("reasons", [])},
            "portfolio_check": result["portfolio_check"],
            "account": account,
            "plan": {"children": plan}}


@router.get("/api/v1/portfolio", tags=["Machine API"])
def get_machine_portfolio(book: str | None = None, authorization: str | None = Header(None),
                          supabase=Depends(get_supabase)):
    """The Portfolio page's payload minus the account number. A read: it works with the kill
    switch off, so a script can always reconcile (spec §1.4). The book served is the KEY's
    (per-book keys, 2026-11-03): no parameter reads the key's own book, a matching one is
    accepted, a mismatched one is a 403."""
    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio import service

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    machine_api.require_scope(supabase, key, "portfolio:read", "GET /api/v1/portfolio")
    book = machine_api.resolve_book(supabase, key, book, "GET /api/v1/portfolio")
    payload = service.portfolio(supabase, book_name=book)
    payload.pop("account_number", None)
    machine_keys.record_event(supabase, key["id"], "GET /api/v1/portfolio", "read")
    return payload


class _ClassificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=12)
    classification: str
    as_of: str
    source: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)


@router.post("/api/v1/forward-file/classifications", tags=["Machine API"],
          status_code=201)
def machine_record_classification(body: _ClassificationIn,
                                  authorization: str | None = Header(None),
                                  supabase=Depends(get_supabase)):
    """Append one print classification to the forward-file store (Loop
    Round 4). The write contract: bearer machine key with the
    `classifications:write` scope (hashed storage, scope-checked and
    audited like every machine route; keys are minted in the admin UI and
    are NOT book-bound for this route -- classifications are reference
    data, not orders, so the orders kill switch does not gate them).
    Body: {ticker, classification in improved|intact|deteriorated, as_of
    (the print/event date, ISO), source?, note?}. The response carries the
    stored row plus `current` -- what the Spec C reader
    (band_crossing.t1_classification) now returns for the name -- so the
    writer verifies the read-back in the same call. Validation failures
    are 422s with the accepted values named; nothing is stored."""
    from tradehub.api import machine_api, machine_keys
    from tradehub.valuation import band_crossing, classifications

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    route = "POST /api/v1/forward-file/classifications"
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    machine_api.require_scope(supabase, key, "classifications:write", route)
    try:
        row = classifications.record_classification(
            supabase, ticker=body.ticker, classification=body.classification,
            as_of=body.as_of, source=body.source, note=body.note,
            recorded_by=key.get("label"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    machine_keys.record_event(
        supabase, key["id"], route, "recorded",
        detail=f"{row['ticker']} {row['classification']} {row['as_of']}")
    recorded = {k: row.get(k) for k in
                ("ticker", "classification", "as_of", "source", "note",
                 "recorded_by", "recorded_at")}
    return {"recorded": recorded,
            "current": band_crossing.t1_classification(supabase,
                                                       row["ticker"])}


class _ForecastCardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=12)
    thesis_slug: str = Field(default="event-lab", max_length=60)
    print_at: str
    whisper_esp: float | None = None
    whisper_sign: str | None = None
    money_flow_direction: str | None = None
    money_flow_evidence: list | None = None
    guide_position: str | None = Field(default=None, max_length=500)
    predicted_direction: str | None = None
    opposing_case_ref: str | None = Field(default=None, max_length=300)
    classification: str | None = None
    supersedes_id: int | None = None


@router.post("/api/v1/thesis/forecast-cards", tags=["Machine API"],
          status_code=201)
def machine_record_forecast_card(body: _ForecastCardIn,
                                 authorization: str | None = Header(None),
                                 supabase=Depends(get_supabase)):
    """Freeze one forecast card (Thesis v6, spec Section 3). The write
    contract: bearer machine key with the `tracker:write` scope. The
    store enforces the freeze -- a card at or after `print_at` is a
    422, as are unknown theses, out-of-vocabulary signal values, and a
    money-flow direction without named evidence. Cards are never
    edited: a correction is a new card with `supersedes_id` set, and
    the response is the stored row so the writer verifies the freeze
    (its `frozen_at` stamp) in the same call."""
    from tradehub.api import machine_api, machine_keys
    from tradehub.tracker import cards

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    route = "POST /api/v1/thesis/forecast-cards"
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    machine_api.require_scope(supabase, key, "tracker:write", route)
    try:
        row = cards.create_card(
            supabase, ticker=body.ticker, thesis_slug=body.thesis_slug,
            print_at=body.print_at, whisper_esp=body.whisper_esp,
            whisper_sign=body.whisper_sign,
            money_flow_direction=body.money_flow_direction,
            money_flow_evidence=body.money_flow_evidence,
            guide_position=body.guide_position,
            predicted_direction=body.predicted_direction,
            opposing_case_ref=body.opposing_case_ref,
            classification=body.classification,
            supersedes_id=body.supersedes_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    machine_keys.record_event(
        supabase, key["id"], route, "recorded",
        detail=f"{row['ticker']} print {row['print_at']}")
    return {"recorded": row}


# ── Machine API step 4: read/cancel for a key's own orders (spec §1.3). Ownership is the ──
# audit trail: an order is yours iff your key placed it. Somebody else's id is a 404, never
# a 403 -- the API does not confirm the order exists.
def _machine_label_tags(supabase) -> dict:
    """Order id -> thesis tag, for the machine views. Enrichment only: a labels
    read that fails must never fail the order read it decorates."""
    try:
        from tradehub.workshop import store as workshop_store

        return workshop_store.label_tags(supabase)
    except Exception:  # noqa: BLE001
        return {}


def _machine_order_view(event: dict, order: dict | None, tag: str | None = None) -> dict:
    if order is None:
        return {"client_order_id": event["client_order_id"], "status": "unknown",
                "event_id": event["id"], "placed_at": event["at"], "tag": tag}
    from tradehub.api.machine_api import broker_order_view

    return {**broker_order_view(order), "client_order_id": event["client_order_id"],
            "event_id": event["id"], "placed_at": event["at"], "tag": tag}


def _machine_group_view(caller_group_id: str, namespaced: str, events: list, broker: dict,
                        tags: dict | None = None) -> dict:
    """One split group as ONE logical order (2026-11-08): aggregate filled quantity,
    the volume-weighted fill price, and the rolled-up status, with the per-child
    views riding along as the breakdown."""
    from tradehub.api import machine_api

    def _tag(order):
        return (tags or {}).get(order.get("id")) if order else None

    views = [_machine_order_view(e, broker.get(e["client_order_id"]),
                                 _tag(broker.get(e["client_order_id"]))) for e in events]
    return {"client_order_id": namespaced, "group_id": caller_group_id, "is_group": True,
            "status": machine_api.rollup_status(views),
            "symbol": views[0].get("symbol") if views else None,
            "side": views[0].get("side") if views else None,
            "qty": sum(v.get("qty") or 0 for v in views),
            "filled_qty": sum(v.get("filled_qty") or 0 for v in views),
            "filled_avg_price": machine_api.weighted_fill_price(views),
            "placed_at": events[0]["at"] if events else None,
            "children": views}


@router.get("/api/v1/orders", tags=["Machine API"])
def list_machine_orders(limit: int = 50, before: int | None = None, status: str | None = None,
                        book: str | None = None,
                        authorization: str | None = Header(None), supabase=Depends(get_supabase)):
    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    machine_api.require_scope(supabase, key, "orders:read", "GET /api/v1/orders")
    if status not in (None, "open", "all"):
        raise HTTPException(status_code=422, detail="status must be open or all")
    book = machine_api.resolve_book(supabase, key, book, "GET /api/v1/orders")
    events = machine_api.placed_events(supabase, key["id"])
    if before is not None:
        events = [e for e in events if e["id"] < before]
    try:
        broker = machine_api.broker_orders(book=book)
        reachable = True
    except AccountNotConnected:
        broker, reachable = {}, False
    tags = _machine_label_tags(supabase)
    views = [_machine_order_view(e, broker.get(e["client_order_id"]),
                                 tags.get(broker[e["client_order_id"]].get("id"))
                                 if broker.get(e["client_order_id"]) else None)
             for e in events]
    for event, view in zip(events, views):  # a split child names its parent group
        detail = event.get("detail") or ""
        if detail.startswith("group:"):
            view["group_id"] = detail[len("group:"):].split(";")[0].strip()
    if status == "open":
        views = [v for v in views if v["status"] in machine_api.OPEN_STATUSES]
    machine_keys.record_event(supabase, key["id"], "GET /api/v1/orders", "read")
    return {"orders": views[: max(1, min(limit, 200))], "broker_reachable": reachable}


@router.get("/api/v1/orders/open", tags=["Machine API"])
def list_open_orders(book: str | None = None, authorization: str | None = Header(None),
                     supabase=Depends(get_supabase)):
    """The staged book as the broker sees it (2026-11-02): every order resting on the
    paper account, whatever placed it -- machine API, the hub's protective machinery, or
    the Alpaca app. The account is the KEY's book (per-book keys, 2026-11-03). Declared
    before /orders/{client_order_id} so "open" is never read as a caller id."""
    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    # The staged book is a portfolio read as much as an order read (2026-11-08):
    # a key holding portfolio:read sees every resting order on its book, each
    # labelled with who placed it, so two readers never collide blind.
    if "orders:read" not in key.get("scopes", []) and "portfolio:read" not in key.get("scopes", []):
        machine_keys.record_event(supabase, key["id"], "GET /api/v1/orders/open",
                                  "refused:scope", detail="needs orders:read or portfolio:read")
        raise HTTPException(status_code=403,
                            detail="this key lacks the orders:read or portfolio:read scope")
    book = machine_api.resolve_book(supabase, key, book, "GET /api/v1/orders/open")
    try:
        orders = machine_api.open_broker_orders(book=book)
        reachable = True
    except AccountNotConnected:
        orders, reachable = [], False
    orders = machine_api.attribute_orders(supabase, orders)
    machine_keys.record_event(supabase, key["id"], "GET /api/v1/orders/open", "read")
    return {"orders": orders, "broker_reachable": reachable}


@router.get("/api/v1/orders/{client_order_id}", tags=["Machine API"])
def get_machine_order(client_order_id: str, authorization: str | None = Header(None),
                      supabase=Depends(get_supabase)):
    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    machine_api.require_scope(supabase, key, "orders:read", "GET /api/v1/orders/{id}")
    namespaced = machine_api.resolve_caller_id(key, client_order_id)
    event = machine_api.owns_event(supabase, key["id"], namespaced)
    if event is None:
        # Not a single order: a split group id reads as the ONE logical order it
        # placed (2026-11-08) -- aggregate fills, weighted price, children attached.
        prefix = f"ext-{key['id']}-"
        caller_form = namespaced[len(prefix):] if namespaced.startswith(prefix) else client_order_id
        children = machine_api.group_events(supabase, key["id"], namespaced, caller_form)
        if not children:
            machine_keys.record_event(supabase, key["id"], "GET /api/v1/orders/{id}",
                                      "refused:ownership", client_order_id=namespaced)
            raise HTTPException(status_code=404, detail="no such order")
        try:
            broker = machine_api.broker_orders(book=machine_api.key_book(key))
        except AccountNotConnected:
            broker = {}
        machine_keys.record_event(supabase, key["id"], "GET /api/v1/orders/{id}", "read",
                                  client_order_id=namespaced)
        return _machine_group_view(caller_form, namespaced, children, broker,
                                   _machine_label_tags(supabase))
    try:
        broker = machine_api.broker_orders(book=machine_api.key_book(key))
    except AccountNotConnected:
        broker = {}
    machine_keys.record_event(supabase, key["id"], "GET /api/v1/orders/{id}", "read",
                              client_order_id=namespaced)
    order = broker.get(namespaced)
    tag = _machine_label_tags(supabase).get(order.get("id")) if order else None
    return _machine_order_view(event, order, tag)


@router.delete("/api/v1/orders/{client_order_id}", tags=["Machine API"])
def cancel_machine_order_route(client_order_id: str, authorization: str | None = Header(None),
                               supabase=Depends(get_supabase)):
    """Cancel one of this key's open orders. A cancel is not a placement: the kill switch
    does not block it (a runaway key's orders must stay cancellable while the switch is off);
    the paper-orders switch inside paper_orders still applies."""
    from tradehub.api import machine_api, machine_keys
    from tradehub.portfolio import paper_orders
    from tradehub.portfolio.alpaca_paper import AccountNotConnected

    if supabase is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    key = machine_api.authenticate(supabase, authorization)
    machine_api.check_rate_limit(key)
    route = "DELETE /api/v1/orders/{id}"
    machine_api.require_scope(supabase, key, "orders:place", route)
    namespaced = machine_api.resolve_caller_id(key, client_order_id)

    def refused(outcome: str, status: int, detail: str):
        machine_keys.record_event(supabase, key["id"], route, f"refused:{outcome}",
                                  detail=detail, client_order_id=namespaced)
        raise HTTPException(status_code=status, detail=detail)

    if machine_api.owns_event(supabase, key["id"], namespaced) is None:
        refused("ownership", 404, "no such order")
    book = machine_api.key_book(key)
    try:
        broker = machine_api.broker_orders(book=book)
    except AccountNotConnected:
        refused("account", 424, "the paper account is not connected")
    order = broker.get(namespaced)
    if order is None:
        refused("broker_missing", 404, "the order is not in the broker's recent window")
    try:
        paper_orders.cancel_machine_order(order["id"], namespaced, book=book)
    except paper_orders.OrdersDisabled as exc:
        refused("paper_switch_off", 409, str(exc))
    except paper_orders.OrderGone:
        refused("gone", 409, "the order already filled or was already cancelled")
    except AccountNotConnected:
        refused("account", 424, "the paper account is not connected")
    except (paper_orders.OrderRejected, ValueError) as exc:
        refused("rejected", 422, str(exc))
    machine_keys.record_event(supabase, key["id"], route, "cancelled",
                              client_order_id=namespaced)
    return {"client_order_id": namespaced, "status": "cancelled"}
