"""The crypto desk's pure build (step 2): brand aggregation over
DefiLlama parents, the multiples, the trend math, and honest nulls."""
from __future__ import annotations

from tradehub.crypto_desk import build_desk

FEES = [
    {"slug": "uniswap-v3", "parentProtocol": "parent#uniswap", "total24h": 1_000_000, "total7d": 14_000_000, "total30d": 30_000_000},
    {"slug": "uniswap-v4", "parentProtocol": "parent#uniswap", "total24h": 500_000, "total7d": 7_000_000, "total30d": 30_000_000},
    {"slug": "ethereum", "parentProtocol": None, "total24h": 250_000, "total7d": 1_750_000, "total30d": 7_500_000},
    {"slug": "lido", "parentProtocol": None, "total24h": 1_500_000, "total7d": 10_500_000, "total30d": 45_000_000},
]
REVENUE = [
    {"slug": "uniswap-v3", "parentProtocol": "parent#uniswap", "total24h": 200_000},
    {"slug": "uniswap-v4", "parentProtocol": "parent#uniswap", "total24h": 100_000},
    {"slug": "ethereum", "parentProtocol": None, "total24h": 250_000},
]
PROTOCOLS = [
    {"slug": "uniswap-v3", "parentProtocol": "parent#uniswap", "tvl": 3_000_000_000},
    {"slug": "uniswap-v4", "parentProtocol": "parent#uniswap", "tvl": 1_000_000_000},
    {"slug": "lido", "parentProtocol": None, "tvl": 20_000_000_000},
]
CHAINS = [{"name": "Ethereum", "tvl": 60_000_000_000}]
MARKETS = [
    {"id": "uniswap", "current_price": 10.0, "market_cap": 6_000_000_000,
     "fully_diluted_valuation": 10_000_000_000, "price_change_percentage_24h": 2.5},
    {"id": "ethereum", "current_price": 3000.0, "market_cap": 360_000_000_000,
     "fully_diluted_valuation": 360_000_000_000, "price_change_percentage_24h": -1.0},
]


def _row(rows, key):
    return next(r for r in rows if r["key"] == key)


def test_brand_aggregation_and_multiples():
    rows = build_desk(FEES, REVENUE, PROTOCOLS, CHAINS, MARKETS)
    uni = _row(rows, "uniswap")
    assert uni["fees_24h"] == 1_500_000  # v3 + v4 summed under the parent
    assert uni["revenue_24h"] == 300_000
    assert uni["tvl"] == 4_000_000_000
    assert uni["pf"] == round(6_000_000_000 / (1_500_000 * 365), 1)
    assert uni["ps"] == round(10_000_000_000 / (300_000 * 365), 1)
    # Trend: 24h run-rate vs the 7d average (21M/7 = 3M/day -> -50%)
    assert uni["fee_trend_7d"] == -50.0
    assert uni["fee_trend_30d"] == -25.0


def test_network_rows_and_tokenless_base():
    rows = build_desk(FEES, REVENUE, PROTOCOLS, CHAINS, MARKETS)
    eth = _row(rows, "ethereum")
    assert eth["kind"] == "network" and eth["fees_24h"] == 250_000
    assert eth["tvl"] == 60_000_000_000  # from the chains payload, not protocols
    base = _row(rows, "base")
    assert base["price"] is None and base["pf"] is None and base["symbol"] is None


def test_thin_fees_null_the_multiples_not_the_fees():
    fees = [{"slug": "ethena-usde", "parentProtocol": "parent#ethena",
             "total24h": 478, "total7d": 3000, "total30d": 12000}]
    rev = [{"slug": "ethena-usde", "parentProtocol": "parent#ethena", "total24h": 478}]
    markets = [{"id": "ethena", "current_price": 0.17, "market_cap": 2_000_000_000,
                "fully_diluted_valuation": 2_500_000_000, "price_change_percentage_24h": 0.5}]
    rows = build_desk(fees, rev, [], [], markets)
    ena = _row(rows, "ethena")
    assert ena["fees_24h"] == 478  # the source's number still shows
    assert ena["pf"] is None and ena["ps"] is None  # but no 11,000x multiple


def test_sort_is_pf_then_unpriced_last():
    rows = build_desk(FEES, REVENUE, PROTOCOLS, CHAINS, MARKETS)
    priced = [r for r in rows if r["pf"] is not None]
    assert [r["pf"] for r in priced] == sorted(r["pf"] for r in priced)
    assert rows[-1]["pf"] is None
