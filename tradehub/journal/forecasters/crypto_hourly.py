"""Kalshi hourly crypto (KXBTC / KXETH), graded against the market and persistence.

The clone of the hourly-oil build with the sigma source swapped, per the
preregistered variant-2 replay (2026-11-02): the model (`crypto_btc_hourly`,
`btc-hourly-v1`; `crypto_eth_hourly`, `eth-hourly-v1`) prices each strike as
a Normal centred on the live spot anchor with a sigma from the trailing 120
minutes of 1-minute realized volatility, scaled by sqrt(time-to-close) --
`engines/crypto_hourly.py` carries the reasoning and the variant-1 failure
that motivated it. Beside each model the journal grades the Kalshi mid
(`KalshiImplied`) and the same persistence baseline oil uses (the last
settled hour's value as the level, trailing settled-hourly sigma stretched
over the span since it). The registry adds the w25 market-shrunk rows from
day one, the oil precedent.

Strictness rule, from the preregistration: when the 1-minute bars are
missing, stale, or too thin at freeze time the forecast is skipped -- the
sigma method is never silently swapped, because a swapped method would
corrupt the forward record the model is graded on.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.crypto_bars import crypto_bars_1m
from tradehub.engines.crypto_hourly import (
    DECISION_LEAD,
    SERIES_SYMBOLS,
    crypto_prob,
    realized_sigma,
)
from tradehub.engines.oil_hourly import event_hour, hourly_changes, hourly_sigma, sigma_for
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.forecasters.baselines import PERSISTENCE, baseline_name
from tradehub.journal.kalshi_linked import (
    KalshiImplied,
    entry_for,
    in_freeze_window,
    kalshi_target,
    quote_mid,
    quote_payload,
    settle_on_kalshi,
)
from tradehub.markets import prob_in_interval, yes_interval
from tradehub.engines.crypto_hourly import CRYPTO_RESOLUTION

LEAD = DECISION_LEAD
MIN_CHANGES = 24          # persistence: a full day of hourly changes before it speaks
RECENT_EVENTS = 120       # settled events to pull per run (per series)
MAX_PRICE_AGE = timedelta(minutes=15)

COINS = (
    {"series": "KXBTC", "family": "crypto_btc_hourly", "name": "crypto_btc_hourly",
     "version": "btc-hourly-v1"},
    {"series": "KXETH", "family": "crypto_eth_hourly", "name": "crypto_eth_hourly",
     "version": "eth-hourly-v1"},
)


class CryptoInputs:
    """Settled hourly values per series and 1-minute bars per symbol, loaded once
    per run (keyed on `now`, the oil inputs' rule)."""

    def __init__(self, live, *, bars_fn: Callable[[str], list] = crypto_bars_1m):
        self._live, self._bars_fn = live, bars_fn
        self._now: datetime | None = None
        self._settled: dict[str, list] = {}
        self._bars: dict[str, list] = {}

    def _refresh(self, now: datetime) -> None:
        if now == self._now:
            return
        self._now = now
        for coin in COINS:
            series = coin["series"]
            recent = getattr(self._live, "settled_values_recent", None)
            values = (recent(series, RECENT_EVENTS) if callable(recent)
                      else self._live.settled_values(series))
            self._settled[series] = [o for o in values if o.published_at <= now]
            self._bars[SERIES_SYMBOLS[series]] = self._bars_fn(SERIES_SYMBOLS[series])

    def settled(self, series: str, now: datetime) -> list:
        self._refresh(now)
        return self._settled[series]

    def bars(self, series: str, now: datetime) -> list:
        self._refresh(now)
        return self._bars[SERIES_SYMBOLS[series]]


class _CryptoBase:
    cadence = "hourly"

    def __init__(self, live, fetch: Callable[[str], Any], inputs: CryptoInputs, coin: dict):
        self._live, self._fetch_market, self._inputs = live, fetch, inputs
        self.series, self.family = coin["series"], coin["family"]
        self._open: dict[str, Any] = {}

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): lm
                      for lm in self._live.open_markets(self.series)
                      if in_freeze_window(lm, now, LEAD)}
        return [entry_for(lm, self.family, self.cadence) for lm in self._open.values()]

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class CryptoHourlyModel(_CryptoBase):
    def __init__(self, live, fetch, inputs, coin):
        super().__init__(live, fetch, inputs, coin)
        self.name, self.version = coin["name"], coin["version"]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        bars = self._inputs.bars(self.series, now)
        if not bars:
            return None
        anchor = bars[-1]
        if now - anchor.published_at > MAX_PRICE_AGE:
            return None  # no live anchor: a gap, never a stale price dressed as live
        minutes = (lm.market.close_time - now).total_seconds() / 60.0
        sigma_rel = realized_sigma(bars, minutes)
        if sigma_rel is None:
            return None  # tape too thin: skip the freeze, never swap the sigma method
        # a 1bp floor: a perfectly flat tape would otherwise price at exactly 0/1
        sigma_price = max(anchor.value * sigma_rel, anchor.value * 1e-4)
        return Forecast(self.name, self.version, entry.target,
                        crypto_prob(lm.market, anchor.value, sigma_price),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "live_price": anchor.value,
                                 "price_at": anchor.published_at.isoformat(),
                                 "sigma_rel": sigma_rel, "sigma_price": sigma_price,
                                 "minutes_to_close": round(minutes, 1),
                                 "basis": "trailing 120m of 1-minute log returns (variant 2, "
                                          "preregistered 2026-11-02)"})


class CryptoHourlyPersistence(_CryptoBase):
    version = "v1"

    def __init__(self, live, fetch, inputs, coin):
        super().__init__(live, fetch, inputs, coin)
        self.name = baseline_name(PERSISTENCE, coin["family"])

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        lm = self._open.get(entry.target)
        if lm is None:
            return None
        settled = self._inputs.settled(self.series, now)
        changes = hourly_changes(settled)
        if len(changes) < MIN_CHANGES:
            return None
        last = max(settled, key=lambda o: event_hour(o.name))
        span_minutes = (lm.market.close_time - event_hour(last.name)).total_seconds() / 60.0
        if span_minutes < 60:
            return None
        sigma = sigma_for(hourly_sigma(changes), span_minutes)
        return Forecast(self.name, self.version, entry.target,
                        prob_in_interval(last.value, sigma,
                                         yes_interval(lm.market, CRYPTO_RESOLUTION)),
                        market_prob=quote_mid(lm),
                        payload={**quote_payload(lm), "last_settlement": last.value,
                                 "last_settlement_event": last.name,
                                 "span_minutes": round(span_minutes, 1), "sigma": sigma,
                                 "basis": "last settled hour's value as the level, trailing "
                                          "hourly sigma stretched over the span since it"})


def build_crypto_hourly(live, fetch: Callable[[str], Any] = fetch_market,
                        inputs: CryptoInputs | None = None) -> list:
    inputs = inputs or CryptoInputs(live)
    out = []
    for coin in COINS:
        out += [CryptoHourlyModel(live, fetch, inputs, coin),
                KalshiImplied(coin["family"], (coin["series"],), "hourly", live, fetch, lead=LEAD),
                CryptoHourlyPersistence(live, fetch, inputs, coin)]
    return out
