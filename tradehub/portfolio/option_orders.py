"""Shared option-order validation for the two hand doors (Kevin, 2026-11-09):
the machine API (/api/v1/orders) and the Portfolio page's hand-order form
(/api/portfolio/orders). One implementation, so the surfaces can never diverge
on what is allowed: OCC parsing, the contract check, the defined-risk guard and
the max-loss math live here; each door adds only its own fences on top (the
machine door's kill switch and per-key caps; the form's admin session).

The defined-risk guard is the load-bearing rule: an order through either door
must never CREATE naked short options exposure. A short leg is covered only by
a long leg in the same package or a long contract already held in the book --
checked post-trade, per (underlying, expiry, kind) group: total longs must be
at least total shorts. Close legs must be backed by contracts actually held.
"""

from __future__ import annotations

import math
from typing import Any

from tradehub.portfolio import options
from tradehub.portfolio.alpaca_paper import AccountNotConnected  # noqa: F401  (re-exported for callers)

INTENTS = ("buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close")
OPEN_INTENTS = ("buy_to_open", "sell_to_open")
CLOSE_INTENTS = ("buy_to_close", "sell_to_close")
NET_PRICE_CONVENTION = ("net limit price: positive is a debit paid, negative is a credit taken "
                        "(Alpaca's mleg convention)")


class OptionOrderError(ValueError):
    """The order's shape is not one either door takes; the message is the refusal."""


def clean_symbol(symbol: Any) -> str:
    """The canonical OCC form: upper-case, no padding spaces (Alpaca pads the root
    to six characters in some payloads; the door speaks the unpadded 21-char form)."""
    return str(symbol or "").strip().upper().replace(" ", "")


def is_option_symbol(symbol: Any) -> bool:
    return options.is_occ(clean_symbol(symbol))


def default_intent(side: str) -> str:
    return "buy_to_open" if side == "buy" else "sell_to_open"


def normalize_leg(raw: dict) -> dict:
    """One leg, validated: a real OCC parse, a buy/sell side, a whole qty, and a
    position intent that agrees with the side (defaulted open when omitted)."""
    symbol = clean_symbol(raw.get("symbol"))
    try:
        parsed = options.parse_occ(symbol)
    except ValueError:
        raise OptionOrderError(
            f"not an OCC option symbol: {raw.get('symbol')!r} "
            "(expected e.g. SPY261113P00570000)") from None
    side = raw.get("side")
    if side not in ("buy", "sell"):
        raise OptionOrderError("each leg's side must be buy or sell")
    try:
        qty = int(raw.get("qty") or 0)
    except (TypeError, ValueError):
        raise OptionOrderError("each leg's qty must be a whole number of contracts") from None
    if qty < 1:
        raise OptionOrderError("each leg's qty must be at least 1 contract")
    intent = raw.get("position_intent") or default_intent(side)
    if intent not in INTENTS:
        raise OptionOrderError(f"position_intent must be one of {', '.join(INTENTS)}")
    if not intent.startswith(side):
        raise OptionOrderError(f"position_intent {intent} does not match side {side}")
    return {"symbol": symbol, "side": side, "qty": qty,
            "position_intent": intent, "parsed": parsed}


def normalize_legs(raw_legs) -> list[dict]:
    """A combo: 2-4 legs sharing ONE underlying and ONE expiry. The single-expiry
    door keeps the defined-risk and max-loss math exact; calendar and diagonal
    combos are out of scope here, stated rather than approximated."""
    if not isinstance(raw_legs, list) or not 2 <= len(raw_legs) <= 4:
        raise OptionOrderError("a combo takes 2-4 legs")
    legs = [normalize_leg(raw) for raw in raw_legs]
    first = legs[0]["parsed"]
    for leg in legs[1:]:
        parsed = leg["parsed"]
        if parsed["underlying"] != first["underlying"] or parsed["expiry"] != first["expiry"]:
            raise OptionOrderError(
                "a combo's legs must share one underlying and one expiry "
                f"({first['underlying']} {first['expiry']} vs "
                f"{parsed['underlying']} {parsed['expiry']})")
    return legs


def parent_and_ratios(legs: list[dict]) -> tuple[int, list[int]]:
    """Map the caller's absolute per-leg quantities onto Alpaca's mleg model:
    leg fill = parent qty x ratio_qty. The gcd keeps the map exact -- buy 6 /
    sell 3 is parent 3 with ratios 2/1, so the legs fill 6 and 3, never a
    multiplied 18/9 or 36/18 (the IBKR combo-quantity lesson)."""
    parent = 0
    for leg in legs:
        parent = math.gcd(parent, int(leg["qty"]))
    parent = parent or 1
    return parent, [int(leg["qty"]) // parent for leg in legs]


def contract(symbol: str, book: str | None) -> dict | None:
    """The broker's contract row for `symbol` on this book, or None when the
    contract does not exist or is not tradable. AccountNotConnected propagates;
    any other read failure propagates too -- an unverifiable contract is an
    unplaceable order, and the caller fails closed."""
    from tradehub.portfolio.alpaca_paper import paper_get

    try:
        row = paper_get(f"/v2/options/contracts/{symbol}", book=book)
    except Exception as exc:
        response = getattr(exc, "response", None)
        if response is not None and getattr(response, "status_code", None) == 404:
            return None
        raise
    if not isinstance(row, dict) or not row:
        return None
    if row.get("tradable") is False or row.get("status") not in (None, "active"):
        return None
    return row


def positions_map(book: str | None) -> dict[str, float]:
    """Symbol -> signed quantity held on this book (options and shares alike;
    the risk math picks out the contracts it understands). Read failures
    propagate: callers fail closed."""
    from tradehub.portfolio.alpaca_paper import paper_get

    out: dict[str, float] = {}
    for row in paper_get("/v2/positions", book=book) or []:
        symbol = clean_symbol(row.get("symbol"))
        if symbol:
            out[symbol] = out.get(symbol, 0.0) + float(row.get("qty") or 0)
    return out


def options_buying_power(book: str | None) -> float | None:
    """The account's options buying power (the field Alpaca reports for option
    orders), falling back to plain buying power; None when the account reports
    neither. Read failures propagate."""
    from tradehub.portfolio.alpaca_paper import paper_get

    account = paper_get("/v2/account", book=book) or {}
    raw = account.get("options_buying_power")
    if raw is None:
        raw = account.get("buying_power")
    return float(raw) if raw is not None else None


def _group_key(parsed: dict) -> tuple:
    return (parsed["underlying"], parsed["expiry"], parsed["kind"])


def check_defined_risk(legs: list[dict], held: dict[str, float]) -> str | None:
    """None when the order is defined-risk, else the refusal reason. Two legs of
    the rule: a close must be backed by contracts actually held, and after the
    order every (underlying, expiry, kind) group it touches must hold at least
    as many long contracts as short -- counting longs already in the book, so a
    short against a held long (or inside a package) is covered, and any other
    short is naked and refused."""
    for leg in legs:
        have = held.get(leg["symbol"], 0.0)
        if leg["position_intent"] == "sell_to_close" and have < leg["qty"]:
            return (f"sell_to_close {leg['qty']} x {leg['symbol']} but only "
                    f"{have:g} contracts are held long in this book")
        if leg["position_intent"] == "buy_to_close" and have > -leg["qty"]:
            return (f"buy_to_close {leg['qty']} x {leg['symbol']} but only "
                    f"{-have:g} contracts are held short in this book")
    groups: dict[tuple, float] = {}
    for symbol, qty in held.items():
        try:
            parsed = options.parse_occ(symbol)
        except ValueError:
            continue  # a share row: shares do not cover an option short at this door
        key = _group_key(parsed)
        groups[key] = groups.get(key, 0.0) + qty
    touched: set[tuple] = set()
    for leg in legs:
        key = _group_key(leg["parsed"])
        touched.add(key)
        groups[key] = groups.get(key, 0.0) + (leg["qty"] if leg["side"] == "buy" else -leg["qty"])
    for underlying, expiry, kind in sorted(touched):
        net = groups.get((underlying, expiry, kind), 0.0)
        if net < -1e-9:
            return (f"net-short {kind}s in {underlying} expiring {expiry}: this order would "
                    f"leave the book short {-net:g} {kind} contracts with no covering long. "
                    "A naked short option is never placed through this door -- cover the "
                    "short with a long leg in the same package or a long contract already "
                    "held in the book")
    return None


def opening_premium(legs: list[dict], prices: dict[str, float]) -> float:
    """Net premium PAID by the opening legs at the given per-contract prices, in
    dollars (negative for a net credit). Closing legs move no premium here --
    their proceeds are the position's own business, not new risk."""
    total = 0.0
    for leg in legs:
        if leg["position_intent"] == "buy_to_open":
            total += prices[leg["symbol"]] * leg["qty"] * 100
        elif leg["position_intent"] == "sell_to_open":
            total -= prices[leg["symbol"]] * leg["qty"] * 100
    return total


def _payoff(parsed: dict, signed_qty: float, spot: float) -> float:
    if parsed["kind"] == "call":
        return signed_qty * max(spot - parsed["strike"], 0.0) * 100
    return signed_qty * max(parsed["strike"] - spot, 0.0) * 100


def max_loss(legs: list[dict], held: dict[str, float], net_premium_total: float) -> float:
    """Worst expiry loss of the order's OPENING legs, in dollars: the payoff over
    candidate underlyings (0, every strike in play, and far above the top strike)
    minus the net premium paid (a credit makes the premium negative). Long debit
    spreads and net-long ratio spreads both reduce to their net debit, exactly.
    Long contracts already held in a touched group count as cover -- their
    expiry payoff is real; their premium is sunk and excluded. Pure closing
    orders risk nothing new: 0."""
    opening = [leg for leg in legs if leg["position_intent"] in OPEN_INTENTS]
    if not opening:
        return 0.0
    touched = {_group_key(leg["parsed"]) for leg in opening}
    terms = [(leg["parsed"], leg["qty"] if leg["side"] == "buy" else -leg["qty"])
             for leg in opening]
    for symbol, qty in held.items():
        if qty <= 0:
            continue
        try:
            parsed = options.parse_occ(symbol)
        except ValueError:
            continue
        if _group_key(parsed) in touched:
            terms.append((parsed, qty))
    strikes = sorted({parsed["strike"] for parsed, _ in terms})
    candidates = [0.0, *strikes, strikes[-1] * 3 + 1000.0]
    worst_payoff = min(sum(_payoff(parsed, qty, spot) for parsed, qty in terms)
                       for spot in candidates)
    return max(0.0, net_premium_total - worst_payoff)
