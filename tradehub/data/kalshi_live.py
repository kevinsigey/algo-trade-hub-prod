"""Kalshi live markets (with top-of-book quotes) and settled values as point-in-time observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from tradehub.backtest.kalshi_history import PAGE_LIMIT, KalshiHistoryClient, parse_ts
from tradehub.backtest.pit import Observation
from tradehub.edges import Quote
from tradehub.markets import KalshiMarket, event_date, parse_market


@dataclass(frozen=True)
class LiveMarket:
    market: KalshiMarket
    quote: Quote


def quote_from_market_raw(raw: dict[str, Any]) -> Quote:
    bid = float(raw.get("yes_bid_dollars") or 0.0)
    ask = float(raw.get("yes_ask_dollars") or 1.0)
    return Quote(
        yes_bid=bid if bid > 0.0 else None,
        yes_ask=ask if ask < 1.0 else None,
        yes_bid_size=float(raw.get("yes_bid_size_fp") or 0.0),
        yes_ask_size=float(raw.get("yes_ask_size_fp") or 0.0),
    )


def safe_event_date(event_ticker: Any) -> date | None:
    """event_date() for well-formed tickers; None for legacy/malformed ones (e.g. HIGHCHI-2-24FEB28)."""
    try:
        return event_date(event_ticker)
    except (TypeError, ValueError, IndexError, AttributeError):
        return None


def settlement_observations(raws: list[dict[str, Any]]) -> list[Observation]:
    """One Observation per event: the settled underlying value and when Kalshi published it."""
    best: dict[str, Observation] = {}
    for raw in raws:
        value = raw.get("expiration_value")
        stamp = raw.get("settlement_ts")
        if value in (None, "") or not stamp:
            continue
        try:
            name = raw["event_ticker"]
            event_date(name)
            obs = Observation(name=name, value=float(value), published_at=parse_ts(stamp))
        except (KeyError, TypeError, ValueError):
            continue
        current = best.get(obs.name)
        if current is None or obs.published_at < current.published_at:
            best[obs.name] = obs
    return sorted(best.values(), key=lambda o: event_date(o.name))


class KalshiLive(KalshiHistoryClient):
    def open_markets(self, series_ticker: str) -> list[LiveMarket]:
        raws = self._paginate("/markets", "markets", {"series_ticker": series_ticker, "status": "open", "limit": PAGE_LIMIT})
        return [LiveMarket(parse_market(r), quote_from_market_raw(r)) for r in raws]

    def settled_values(self, series_ticker: str) -> list[Observation]:
        return settlement_observations(self.settled_markets(series_ticker))

    def settled_values_recent(self, series_ticker: str, max_events: int,
                              max_pages: int = 6) -> list[Observation]:
        """Settled values for the most recent `max_events` events, newest first page order.

        High-cadence series (hourly WTI settles ~30 markets an event, hundreds a day)
        make the full-history `settled_values` pull grow without bound; a sigma fit only
        ever reads the trailing window. Pages come back newest-first (verified live
        2026-11-01: page one of KXWTIH settled held the latest hours), so pagination
        stops as soon as enough distinct events are in hand, with `max_pages` as the
        hard bound on what one call can cost.
        """
        raws: list[dict[str, Any]] = []
        events: set[str] = set()
        cursor = None
        for _ in range(max_pages):
            params: dict[str, Any] = {"series_ticker": series_ticker, "status": "settled",
                                      "limit": PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            data = self._get("/markets", params)
            page = data.get("markets") or []
            raws.extend(page)
            events.update(raw.get("event_ticker") for raw in page)
            cursor = data.get("cursor")
            if not cursor or len(events) >= max_events:
                break
        return settlement_observations(raws)
