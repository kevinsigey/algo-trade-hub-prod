"""The forecasters the journal job runs. Plans (b)-(f) append theirs here, one line each.

Constructing a forecaster must not touch the network: clients are built here, used only when the
runner calls `targets`/`forecast`/`settle`.
"""

from __future__ import annotations

from tradehub.core.kalshi_feed import fetch_market
from tradehub.core.supabase_client import get_client
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.contract import Forecaster
from tradehub.journal.daily import DailyCloses
from tradehub.journal.forecasters.baselines import build_baselines
from tradehub.journal.forecasters.calibrated import CalibratedForecaster
from tradehub.journal.forecasters.claims import build_claims
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.daily_direction import build_wave2, wave2_closes
from tradehub.journal.forecasters.ercot import build_ercot
from tradehub.journal.forecasters.gas import build_gas
from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, UnrateDirection
from tradehub.journal.forecasters.news_tone import (
    SECTORS,
    EnergyToneForecaster,
    build_sector_tone,
    etf_source,
    xle_source,
)
from tradehub.journal.forecasters.crypto_hourly import build_crypto_hourly
from tradehub.journal.forecasters.natgas_daily import build_natgas_daily
from tradehub.journal.forecasters.oil import build_brent, build_oil
from tradehub.journal.forecasters.oil_hourly import build_oil_hourly
from tradehub.journal.forecasters.oil_geo import build_oil_geo_shadow
from tradehub.journal.forecasters.oil_geo2 import build_oil_geo2
from tradehub.journal.forecasters.fifteen_min import build_fifteen_min
from tradehub.journal.forecasters.oil_pyth import build_oil_hl_shadow, build_oil_pyth_shadow
from tradehub.journal.forecasters.ppi import build_ppi
from tradehub.journal.forecasters.unrate_level import build_unrate
from tradehub.journal.forecasters.sentiment import SentimentMeter
from tradehub.journal.forecasters.shrunk import MarketShrunk
from tradehub.journal.forecasters.sports import SportsFeedForecaster, build_sports
from tradehub.journal.forecasters.spy_quant import SpyQuant
from tradehub.journal.forecasters.weather import build_weather
from tradehub.journal.kalshi_linked import KalshiImplied
from tradehub.journal.spx import SpxCloses

_LIVE = KalshiLive()
_LABOR = LaborData()
_SPX = SpxCloses()
# One closes object per wave-2 family, given to BOTH the model and its naive baselines (see
# `baselines.py`: the climatology a baseline freezes has to be the one the calendar carries).
_WAVE2 = wave2_closes()
# phase-2 §5.1: XLE closes for the energy news-tone row (its own object, shared with its baselines).
_XLE = DailyCloses(xle_source())
_SECTOR_CLOSES = {sector: DailyCloses(etf_source(etf))
                  for sector, (_basket, etf) in SECTORS.items() if sector != "energy"}

FORECASTERS: list[Forecaster] = [
    # plan (b): CPI + FOMC, each beside its Kalshi pseudo-forecaster (spec §5, ruling Q5)
    CpiForecaster("KXCPI", _LIVE, fetch_market),
    CpiForecaster("KXCPICORE", _LIVE, fetch_market),
    KalshiImplied("cpi", ("KXCPI", "KXCPICORE"), "monthly", _LIVE, fetch_market),
    # Retired/parked 2026-11-01 (macro audit, Kevin's call): fomc_mapped is RETIRED --
    # a fixed mapping with no model, pre-registered by its own authors as the first
    # retirement candidate; its market row and cautious copy go with it (the series
    # stays available to a future real Fed model). quits_direction and
    # housing_direction are PARKED -- code kept, no longer frozen or graded
    # (quits had 0 settled in five weeks; housing prints two months stale with a
    # ~4-year path to its gate). Their journal history is untouched.
    # plan (c): labor (spec §5); payrolls beside the market, the direction fits vs climatology
    PayrollsForecaster(_LIVE, fetch_market, _LABOR),
    KalshiImplied("labor", ("KXPAYROLLS",), "monthly", _LIVE, fetch_market),
    UnrateDirection(_LIVE, _LABOR),
    # KXU3 level (2026-11-01 audit: build): the market-graded successor to the direction
    # row -- the level model, the market itself and persistence on the same labor data
    *build_unrate(_LIVE, fetch_market, _LABOR),
    # plan (d): sentiment meter (spec §6)
    SentimentMeter(_SPX),
    # plan (e): walk-forward quant (spec §7); same target and settlement as the meter
    SpyQuant(_SPX),
    # wave 2 (spec §8): VIX, gold (GLD) and EUR/USD daily direction, same walk-forward model
    *build_wave2(_WAVE2),
    # phase-2 §5.1: energy news tone -> XLE direction, the fixed logistic z map, graded as-is
    EnergyToneForecaster(_XLE),
    # sector tone (2026-11-01, Kevin's generalization): the same fixed map for
    # every other SPDR sector against its own ETF, each on its own record
    *build_sector_tone(_SECTOR_CLOSES),
    # spec §8/§10: the naive baselines -- persistence and climatology for every non-market direction
    # family, each beside the model whose targets it prices, on the same closes and its own calendar.
    # Never promoted and never counted as evidence: see `forecasters/baselines.py` and `scoring.py`.
    *build_baselines(_SPX, _WAVE2, None,
                     {"xle": _XLE,
                      **{etf.lower(): _SECTOR_CLOSES[sector]
                         for sector, (_b, etf) in SECTORS.items() if sector != "energy"}}),
    # wave 3 (spec §8): NFL and CFB feed consumers, each beside its Kalshi-implied baseline
    *build_sports(),
    # daily weather (highs, lows, rain): NOAA/ECMWF ensembles beside the Kalshi mid and station climatology
    *build_weather(_LIVE, store=get_client),
    # ERCOT daily peak demand: a temperature regression beside the Kalshi mid and a weekday baseline
    *build_ercot(_LIVE),
    # AAA daily gasoline: the RBOB regression beside the Kalshi mid and a persistence baseline
    *build_gas(_LIVE),
    # WTI daily crude (2026-11-01 audit: build): the CL=F regression beside the Kalshi mid
    # and a persistence baseline
    *build_oil(_LIVE),
    # Brent daily (KXBRENTD, 2026-11-01): the daily model's sibling on the Pyth Brent
    # index, BZ=F closes through the same loader (Kalshi has no Brent hourly series)
    *build_brent(_LIVE),
    # WTI hourly (2026-11-01, Kevin's queue): the live-price/sigma model beside the Kalshi
    # mid and a persistence baseline; the first hourly-cadence family in the journal
    *build_oil_hourly(_LIVE),
    # Geo shadow (2026-11-02, chokepoints plan addition 1): the hourly WTI row again with
    # sigma widened by the Hormuz stress tier -- shadow only, preregistered paired-Brier
    # gate at 200 settled (design: shadow-features-design-2026-11-02.md). v1 is untouched.
    *build_oil_geo_shadow(_LIVE),
    # Geo2 shadows (2026-11-04, Kevin's queue): the sensitive continuous Hormuz
    # stress (geo/stress.py) widening sigma on the hourly WTI, daily WTI and
    # daily natgas models -- each its own shadow row, bases untouched.
    *build_oil_geo2(_LIVE),
    # Pyth shadow (2026-11-04, on Kevin's 14-day trial): v1 with only the anchor swapped for the feed
    # Kalshi settles on, to test whether the delayed CL=F price is why v1 trails the market.
    *build_oil_pyth_shadow(_LIVE),
    *build_oil_hl_shadow(_LIVE),
    # 15-minute direction (2026-11-04, Kevin's queue): KXWTI15M / KXBRENT15M /
    # KXNATGAS15M shadows on the Hyperliquid tape -- the drift-scaled walk in
    # engines/fifteen_min.py, preregistered; the journal's hourly phase samples
    # the :15 window each hour (see the forecaster's docstring).
    *build_fifteen_min(_LIVE),
    # Crypto hourly (2026-11-02, Kevin's crypto program step 1): the oil-hourly clone
    # with realized-vol sigma (preregistered variant 2 passed its replay gate on both
    # series; the settled-sigma variant 1 tied persistence and never shipped)
    *build_crypto_hourly(_LIVE),
    # Natural gas daily (2026-11-03, handover item 5): KXNATGASD settles on the Pyth
    # NATGAS index at 17:00 ET; the hourly-WTI construction at a daily grain (NG=F
    # anchor, settled-daily sigma) beside the Kalshi mid and a persistence baseline.
    # EIA storage and the degree-day tilt are NOT in v1 -- each would be its own
    # shadow row (storage also waits on Kevin's free EIA key).
    *build_natgas_daily(_LIVE),
    # weekly jobless claims (2026-11-01 audit: build): the first-print level model beside
    # the Kalshi mid and a persistence baseline
    *build_claims(_LIVE),
    # monthly PPI YoY (2026-11-01 audit: medium add): the fitted level model beside
    # the Kalshi mid and a persistence baseline; journal-only, no Macro card
    *build_ppi(_LIVE),
]

# plan 15: the market-linked models again, each pulled toward the Kalshi price (see forecasters/shrunk.py).
# Their own scorecards, beside the pure models', which are untouched.
_SHRINKABLE = {"cpi_nowcast", "labor_nowcast", "claims_nowcast", "unrate_nowcast", "ppi_nowcast"}
# Order matters and is relied on: `run_journal` walks the list, so each wrapper finds the model's own
# frozen row already in the store (see forecasters/shrunk.py). The store is passed as a callable
# because this module is imported with no credentials in hand.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name in _SHRINKABLE or f.name.startswith("sports_")]

# Model-improvement plan: calibrated versions of sports forecasters beside the originals.
# Wraps the raw sports forecaster (not the MarketShrunk copy) and applies post-hoc calibration
# fitted walk-forward on settled journal rows with earlier cutoffs. No change to scan.py.
FORECASTERS += [CalibratedForecaster(f, get_client) for f in list(FORECASTERS)
                if isinstance(f, SportsFeedForecaster)]

# Phase-3 §3.2 step 3: the weather blend row -- MarketShrunk over the ens-v2
# forecasters only, so each weather family gains a `weather_*_cautious` row at
# version "ens-v2.1+w25" (the model was bumped to ens-v2.1 on 2026-11-01 with
# the audit's levers -- recency-weighted fit, Platt rain calibration, per-model
# payload capture -- before v2 had settled a single contract, so the promotion
# gate restarts cleanly on the improved line): probability = market + 0.25 *
# (model - market), the
# house's pre-registered shrink weight (shrunk.py's ruling: set once, never
# tuned on journal results). Version-pinned because ens-v1 and ens-v2 share
# forecaster names; v1 gets no blend row -- its record stays the raw one the
# phase-3 measurements were taken on.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if getattr(f, "version", None) == "ens-v2.1" and f.name.startswith("weather_")]

# Oil (2026-11-01): the cautious row from day one -- the audit's note on gas was that it
# never got one, so its only journal presence was the raw row that lost paired by ~11x.
# Version-pinned to wti-v1 so a future wti-v2 does not silently inherit the blend.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name == "oil_wti" and getattr(f, "version", None) == "wti-v1"]

# Brent daily (2026-11-01): the same day-one cautious row, pinned to brent-v1.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name == "oil_brent" and getattr(f, "version", None) == "brent-v1"]

# Hourly oil (2026-11-01): the same day-one cautious row, pinned to wti-hourly-v1.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name == "oil_wti_hourly" and getattr(f, "version", None) == "wti-hourly-v1"]

# Hourly crypto (2026-11-02): the same day-one cautious rows, pinned to the v1 lines.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name in ("crypto_btc_hourly", "crypto_eth_hourly")
                and getattr(f, "version", None) in ("btc-hourly-v1", "eth-hourly-v1")]

# Gas cautious (2026-11-02): gas finally gets its cautious row, pinned to the v2 line.
# The crude-feature v3 candidate was rejected by its walk-forward replay (paired Brier
# +0.0029 +/- 0.0012 vs v2), so it never shipped. MarketShrunk adds a separate row; the
# raw v2 record -- the audit's completed measurement -- stays exactly as it was.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name == "gas" and getattr(f, "version", None) == "v2"]

# Natural gas daily (2026-11-03): the day-one cautious row, pinned to natgas-v1.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name == "natgas_daily" and getattr(f, "version", None) == "natgas-v1"]
