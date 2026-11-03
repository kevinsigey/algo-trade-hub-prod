"""Row-click quote payload: a thin seam over the screening data layer, so
the API endpoint stays wiring-only and the payload logic is testable
without yfinance.
"""

from __future__ import annotations


def quote_payload(store, ticker: str) -> dict | None:
    """The quote dict for one ticker, or None when the source has no data."""
    return store.quote_series(ticker)
