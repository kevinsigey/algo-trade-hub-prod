"""Natural gas futures (front month, continuous NG=F) live print.

The daily natgas model's anchor: KXNATGASD settles on the Pyth NATGAS index
at 17:00 ET, and NG=F is the liquid Henry Hub tape beside it -- the same
arrangement as CL=F under the Pyth WTI settlements (data/wti.py). Yahoo's
tape runs minutes behind the exchange; the Observation carries its bar
time so the forecaster can refuse a stale print. The futures-vs-index
basis is not corrected anywhere; the journal's graded record measures it.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any, Callable

from tradehub.backtest.pit import Observation

NATGAS_SYMBOL = "NG=F"


def _default_intraday_history() -> Any:
    import yfinance as yf

    return yf.Ticker(NATGAS_SYMBOL).history(period="1d", interval="1m", auto_adjust=False)


def natgas_last_price(
    *,
    history_fn: Callable[[], Any] = _default_intraday_history,
) -> Observation | None:
    """The latest NG=F 1-minute close as an Observation stamped with its bar time."""
    frame = history_fn()
    if frame is None or "Close" not in frame:
        return None
    for stamp, close in reversed(list(frame["Close"].items())):
        if close is None or close != close:  # NaN check without requiring pandas.
            continue
        stamp = stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)
        return Observation("NATGAS:NG=F:last", float(close), stamp.astimezone(timezone.utc))
    return None
