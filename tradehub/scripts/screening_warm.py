"""Nightly screener warm-up (Kevin, 2026-11-03).

Prefetches the per-ticker data kinds the screener's fields read (info,
statements, earnings dates) for the refreshed S&P 500 + Nasdaq-100 lists,
so a run during the day reads the local cache instead of fetching one name
at a time from rate-limited free sources. Runs after the daily universe
refresh. Options chains are deliberately excluded: their cache TTL is 6h,
so a nightly warm would expire before the evening, and runs now prefetch
them concurrently on demand.
"""

from __future__ import annotations

from tradehub.screening.sources import DataStore
from tradehub.screening.universes import resolve_universe

_KINDS = {"info", "statements", "earnings"}


def main() -> None:
    store = DataStore()
    tickers: set[str] = set()
    for idx in ("sp500", "nasdaq100"):
        try:
            tickers.update(resolve_universe(store, {"type": "index", "index": idx}))
        except Exception as e:  # one missing list must not skip the other
            print(f"screening_warm: universe {idx} unavailable: {e}")
    store.warm(sorted(tickers), _KINDS)
    print(f"screening_warm: warmed {len(tickers)} tickers for {sorted(_KINDS)}; "
          f"missing notes: {len(store.missing)}")


if __name__ == "__main__":
    main()
