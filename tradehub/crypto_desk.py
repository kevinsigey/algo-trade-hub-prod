"""The crypto desk (Kevin's program step 2, scope set 2026-11-03):
protocols and networks read like companies -- price, market cap, FDV,
24h fees and revenue, the annualized P/F and P/S multiples, the fee
trend against its own 7d/30d run-rate, and TVL. Sources are all free
and keyless: DefiLlama for fees (overview, aggregated per brand over
its products), revenue (the same overview with dataType=dailyRevenue),
TVL (protocols + chains) and CoinGecko markets for price/mcap/FDV.

Honesty rules: a missing source nulls only its own fields; a brand with
no token (Base) shows no price row values rather than invented ones;
token unlocks are NOT shown -- no reliable free schedule was verified
(checked 2026-11-03), and an invented unlock calendar is worse than
none. Server-cached 5 minutes: the page polls, the upstreams don't
scale with viewers.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import httpx

LLAMA = "https://api.llama.fi"
GECKO = "https://api.coingecko.com/api/v3"
CACHE_SECONDS = 300.0
# Below this, an annualized multiple is noise wearing a suit (Ethena's
# llama fee adapter reports a few hundred dollars a day): show the fees,
# null the multiple.
MIN_FEES_FOR_MULTIPLE = 10_000.0

# key, display, kind, fee-group rule, gecko id (None = no token).
# Protocols group by DefiLlama's parentProtocol; Sky files under Maker
# (its pre-rebrand parent) in both llama datasets -- verified 2026-11-03.
BRANDS: list[dict[str, Any]] = [
    {"key": "ethereum", "name": "Ethereum", "kind": "network", "chain_slug": "ethereum", "gecko": "ethereum", "symbol": "ETH"},
    {"key": "solana", "name": "Solana", "kind": "network", "chain_slug": "solana", "gecko": "solana", "symbol": "SOL"},
    {"key": "tron", "name": "Tron", "kind": "network", "chain_slug": "tron", "gecko": "tron", "symbol": "TRX"},
    {"key": "base", "name": "Base", "kind": "network", "chain_slug": "base", "gecko": None, "symbol": None},
    {"key": "arbitrum", "name": "Arbitrum", "kind": "network", "chain_slug": "arbitrum", "gecko": "arbitrum", "symbol": "ARB"},
    {"key": "hyperliquid", "name": "Hyperliquid", "kind": "protocol", "parent": "parent#hyperliquid", "gecko": "hyperliquid", "symbol": "HYPE"},
    {"key": "uniswap", "name": "Uniswap", "kind": "protocol", "parent": "parent#uniswap", "gecko": "uniswap", "symbol": "UNI"},
    {"key": "aave", "name": "Aave", "kind": "protocol", "parent": "parent#aave", "gecko": "aave", "symbol": "AAVE"},
    {"key": "lido", "name": "Lido", "kind": "protocol", "slug": "lido", "gecko": "lido-dao", "symbol": "LDO"},
    {"key": "jupiter", "name": "Jupiter", "kind": "protocol", "parent": "parent#jupiter", "gecko": "jupiter-exchange-solana", "symbol": "JUP"},
    {"key": "ethena", "name": "Ethena", "kind": "protocol", "parent": "parent#ethena", "gecko": "ethena", "symbol": "ENA"},
    {"key": "sky", "name": "Sky (Maker)", "kind": "protocol", "parent": "parent#maker", "gecko": "sky", "symbol": "SKY"},
    {"key": "pump", "name": "pump.fun", "kind": "protocol", "parent": "parent#pump", "gecko": "pump-fun", "symbol": "PUMP"},
    {"key": "pendle", "name": "Pendle", "kind": "protocol", "parent": "parent#pendle", "gecko": "pendle", "symbol": "PENDLE"},
    {"key": "morpho", "name": "Morpho", "kind": "protocol", "parent": "parent#morpho", "gecko": "morpho", "symbol": "MORPHO"},
]


def _sum(rows: list[dict], field: str) -> float | None:
    vals = [float(r[field]) for r in rows if r.get(field) is not None]
    return sum(vals) if vals else None


def _brand_rows(overview_rows: list[dict], brand: dict) -> list[dict]:
    if brand["kind"] == "network":
        return [r for r in overview_rows if r.get("slug") == brand["chain_slug"]]
    if "parent" in brand:
        return [r for r in overview_rows if r.get("parentProtocol") == brand["parent"]]
    return [r for r in overview_rows if r.get("slug") == brand.get("slug")]


def _brand_tvl(protocols: list[dict], chains: list[dict], brand: dict) -> float | None:
    if brand["kind"] == "network":
        row = next((c for c in chains if (c.get("name") or "").lower() == brand["key"]), None)
        return float(row["tvl"]) if row and row.get("tvl") is not None else None
    if "parent" in brand:
        vals = [float(p["tvl"]) for p in protocols
                if p.get("parentProtocol") == brand["parent"] and p.get("tvl")]
        return sum(vals) if vals else None
    row = next((p for p in protocols if p.get("slug") == brand.get("slug")), None)
    return float(row["tvl"]) if row and row.get("tvl") is not None else None


def _trend(current: float | None, window_total: float | None, days: float) -> float | None:
    if current is None or not window_total:
        return None
    return round((current / (window_total / days) - 1) * 100, 1)


def build_desk(fees_rows: list[dict], revenue_rows: list[dict], protocols: list[dict],
               chains: list[dict], markets: list[dict]) -> list[dict]:
    """Pure: the desk rows from the five source payloads. Sorted by P/F
    (cheapest first), unpriced rows last."""
    by_gecko = {m.get("id"): m for m in markets}
    out = []
    for brand in BRANDS:
        fees = _brand_rows(fees_rows, brand)
        rev = _brand_rows(revenue_rows, brand)
        fees24, fees7, fees30 = _sum(fees, "total24h"), _sum(fees, "total7d"), _sum(fees, "total30d")
        rev24 = _sum(rev, "total24h")
        mkt = by_gecko.get(brand["gecko"]) if brand.get("gecko") else None
        price = mkt.get("current_price") if mkt else None
        mcap = mkt.get("market_cap") if mkt else None
        fdv = mkt.get("fully_diluted_valuation") if mkt else None
        out.append({
            "key": brand["key"], "name": brand["name"], "kind": brand["kind"],
            "symbol": brand.get("symbol"),
            "price": price,
            "change_24h": mkt.get("price_change_percentage_24h") if mkt else None,
            "mcap": mcap, "fdv": fdv,
            "fees_24h": fees24, "revenue_24h": rev24,
            "pf": round(mcap / (fees24 * 365), 1)
                  if mcap and fees24 and fees24 >= MIN_FEES_FOR_MULTIPLE else None,
            "ps": round(fdv / (rev24 * 365), 1)
                  if fdv and rev24 and fees24 and fees24 >= MIN_FEES_FOR_MULTIPLE else None,
            "fee_trend_7d": _trend(fees24, fees7, 7),
            "fee_trend_30d": _trend(fees24, fees30, 30),
            "tvl": _brand_tvl(protocols, chains, brand),
        })
    out.sort(key=lambda r: (r["pf"] is None, r["pf"] or 0.0, -(r["mcap"] or 0)))
    return out


def _get_json(url: str) -> Any:
    with httpx.Client(timeout=40.0, follow_redirects=True) as client:
        res = client.get(url, headers={"User-Agent": "tradehub-crypto-desk"})
        res.raise_for_status()
        return res.json()


def _fetch_all() -> tuple[dict[str, list], dict[str, str]]:
    gecko_ids = ",".join(b["gecko"] for b in BRANDS if b.get("gecko"))
    urls = {
        "fees": f"{LLAMA}/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true",
        "revenue": f"{LLAMA}/overview/fees?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true&dataType=dailyRevenue",
        "protocols": f"{LLAMA}/protocols",
        "chains": f"{LLAMA}/v2/chains",
        "markets": f"{GECKO}/coins/markets?vs_currency=usd&ids={gecko_ids}&price_change_percentage=24h",
    }
    data: dict[str, list] = {}
    health: dict[str, str] = {}

    def one(name: str, url: str) -> None:
        try:
            payload = _get_json(url)
            rows = payload.get("protocols") if isinstance(payload, dict) else payload
            data[name] = rows if isinstance(rows, list) else []
            health[name] = "live"
        except Exception:  # noqa: BLE001 -- one dead source nulls only its own fields
            data[name] = []
            health[name] = "down"

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda kv: one(*kv), urls.items()))
    return data, health


_cache: dict[str, Any] = {"at": 0.0, "payload": None}


def desk() -> dict[str, Any]:
    now_s = time.monotonic()
    if _cache["payload"] is not None and now_s - _cache["at"] < CACHE_SECONDS:
        return _cache["payload"]
    data, health = _fetch_all()
    payload = {
        "as_of": datetime.now(UTC).isoformat(),
        "sources": health,
        "rows": build_desk(data["fees"], data["revenue"], data["protocols"],
                           data["chains"], data["markets"]),
    }
    _cache.update(at=now_s, payload=payload)
    return payload
