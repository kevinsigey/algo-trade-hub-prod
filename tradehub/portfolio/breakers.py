"""Book-level circuit breakers: a daily loss limit and a drawdown limit, per book.

Off until Kevin sets a number, so nothing here changes trading by default:
TRADEHUB_BREAKER_DAILY_LOSS_PCT and TRADEHUB_BREAKER_MAX_DD_PCT for the main book, the same names
ending _BIG for the $1M book. Tripped, new opening orders are refused; closing and protective
orders still pass. With a limit set, an unreadable account counts as tripped.
"""

from __future__ import annotations

import os

_SUFFIX = {"main": "", "big": "_BIG"}
KIND = "breaker"


def _limit(name: str, book: str) -> float | None:
    raw = os.getenv(f"{name}{_SUFFIX[book]}", "").strip()
    if not raw:
        return None
    value = float(raw)
    if value <= 0:
        raise ValueError(raw)
    return value


def limits(book: str) -> tuple[float | None, float | None]:
    return _limit("TRADEHUB_BREAKER_DAILY_LOSS_PCT", book), _limit("TRADEHUB_BREAKER_MAX_DD_PCT", book)


def _state(daily: float | None, drawdown: float | None, reasons: list[str], **numbers) -> dict:
    return {"enabled": daily is not None or drawdown is not None, "tripped": bool(reasons), "reasons": reasons,
            "daily_limit_pct": daily, "drawdown_limit_pct": drawdown, "daily_loss_pct": None,
            "drawdown_pct": None, "high_water": None, **numbers}


def evaluate(*, equity: float, last_equity: float | None, high_water: float, daily: float | None,
             drawdown: float | None) -> dict:
    loss = max((last_equity - equity) / last_equity * 100, 0.0) if last_equity else None
    fall = max((high_water - equity) / high_water * 100, 0.0) if high_water > 0 else 0.0
    reasons = []
    if daily is not None:
        if loss is None:
            reasons.append("yesterday's equity could not be read, so the daily loss is unknown")
        elif loss >= daily:
            reasons.append(f"daily loss {loss:.2f}% is at or past the {daily:g}% limit")
    if drawdown is not None and fall >= drawdown:
        reasons.append(f"drawdown {fall:.2f}% is at or past the {drawdown:g}% limit")
    return _state(daily, drawdown, reasons, daily_loss_pct=loss, drawdown_pct=fall, high_water=high_water)


def check(supa, book: str, *, read_account=None, read_snapshots=None) -> dict:
    """The book's breaker state, read fresh. Never raises: a limit it can't check counts as tripped."""
    try:
        daily, drawdown = limits(book)
    except ValueError:
        return _state(None, None, [f"a TRADEHUB_BREAKER_DAILY_LOSS_PCT or _MAX_DD_PCT value for {book} isn't a "
                                   "positive number"]) | {"enabled": True}
    if daily is None and drawdown is None:
        return _state(None, None, [])
    try:
        from tradehub.portfolio import service
        from tradehub.portfolio.alpaca_paper import paper_get

        account = (read_account or (lambda: paper_get("/v2/account", book=book)))()
        snaps = (read_snapshots or service.read_snapshots)(supa, account.get("account_number"))
        equity = float(account["equity"])
        last = float(account["last_equity"]) if account.get("last_equity") else None
        return evaluate(equity=equity, last_equity=last, high_water=max([equity, *(float(s["equity"]) for s in snaps)]),
                        daily=daily, drawdown=drawdown)
    except Exception as exc:  # noqa: BLE001 -- fails closed
        return _state(daily, drawdown, [f"the account could not be read ({type(exc).__name__}), so the limits can't be checked"])


def notify(supa, book: str, state: dict) -> None:
    """One open notice per book until Kevin resolves it."""
    from tradehub.workshop import store

    store.add_manual_action(supa, book, None, KIND, None,
                            f"Circuit breaker tripped: {'; '.join(state['reasons'])}. New opening orders are "
                            "refused; closing and protective orders still pass.")


def closes_position(side: str, qty: float, held: float) -> bool:
    """True when the order only shrinks the position: it can't add to it or flip it."""
    return (side == "sell" and 0 < qty <= held) or (side == "buy" and 0 < qty <= -held)
