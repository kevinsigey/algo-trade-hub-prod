"""The paper books the hub can read and trade (Kevin, 2026-11-02).

Two Alpaca paper accounts run side by side: ``main`` (the original ~$100k book, the public
record since October) and ``big`` (a $1M paper account Kevin already had). They are
independent on purpose -- different ideas can be live on each, at different sizes -- so
everything account-shaped takes a book name and defaults to ``main``: every caller written
before the second book keeps meaning the main book. The runner sets the current book with
:func:`use_book` for its second pass; the API threads the name explicitly.

Credentials and kill switches are per book (env names below), so the big book can be
switched off without touching the main book's orders.
"""

from __future__ import annotations

import contextvars
import os

BOOKS: dict[str, dict[str, str]] = {
    "main": {"label": "Main book", "detail": "$100k paper account",
             "key_env": "ALPACA_API_KEY", "secret_env": "ALPACA_SECRET_KEY",
             "orders_env": "TRADEHUB_PAPER_ORDERS"},
    "big": {"label": "$1M book", "detail": "$1M paper account",
            "key_env": "ALPACA_API_KEY_2", "secret_env": "ALPACA_SECRET_KEY_2",
            "orders_env": "TRADEHUB_PAPER_ORDERS_BIG"},
}

_current: contextvars.ContextVar[str] = contextvars.ContextVar("tradehub_book", default="main")


def names() -> list[str]:
    return list(BOOKS)


def resolve(book: str | None = None) -> str:
    """The book a call means: the explicit name, else the runner's current book, else main."""
    name = book or _current.get()
    if name not in BOOKS:
        raise ValueError(f"unknown book {name!r} (known: {', '.join(BOOKS)})")
    return name


def use_book(book: str):
    """Set the current book for this context (the order runner's per-book pass)."""
    return _current.set(resolve(book))


def reset_book(token) -> None:
    _current.reset(token)


def orders_enabled(book: str | None = None) -> bool:
    env = BOOKS[resolve(book)]["orders_env"]
    return os.getenv(env, "").strip().strip('"') == "on"


def auto_trader_enabled() -> bool:
    """The auto-trader's own master switch (Kevin, 2026-11-12): the morning order
    runner and the protective-stop job place orders only when TRADEHUB_AUTO_TRADER
    is exactly "on". It defaults OFF, unlike the per-book switches above: those
    stay on because Kevin's own orders and the machine keys' orders funnel through
    the same order path and are a different flow entirely. Switched off after the
    runner re-bought positions Kevin had deliberately exited, off stale sim-era
    idea weights; it stays off until those weights are reconciled."""
    return os.getenv("TRADEHUB_AUTO_TRADER", "").strip().strip('"') == "on"
