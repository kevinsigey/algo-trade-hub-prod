"""Universe builders. A spec's `universe` is one of:
  {"type": "list", "tickers": [...]}                    explicit list
  {"type": "index_proxy", "index": "spx_liquid_50"}     bundled liquid proxies
  {"type": "sector", "sector": "Technology",
   "base": <any universe object>}                      sector cut of a base

The index proxies are curated static lists of the most liquid constituents
(as of the Nov 2026 build) — labelled proxies, not licensed index membership.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _refreshed(name: str) -> list[str] | None:
    """The daily-refreshed list for `name` from the screening cache, if present."""
    f = Path(os.environ.get("TRADEHUB_SCREENING_CACHE", "/cache/screening")) / f"universe_{name}.json"
    try:
        data = json.loads(f.read_text())
        return list(data["tickers"]) or None
    except Exception:
        return None


def refresh_info() -> dict:
    """Per refreshed universe: when the daily refresh last landed, from
    what source, and how many names -- or None when no refresh has
    landed and the bundled proxy is serving (shown on the Screens page;
    an unstamped universe is how a stale list hides)."""
    out: dict = {}
    cache = Path(os.environ.get("TRADEHUB_SCREENING_CACHE", "/cache/screening"))
    for name in REFRESHED:
        try:
            data = json.loads((cache / f"universe_{name}.json").read_text())
            out[name] = {"as_of": data.get("as_of"),
                         "source": data.get("source"),
                         "count": len(data.get("tickers") or [])}
        except Exception:
            out[name] = None
    return out

SPX_LIQUID_50 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK-B",
    "JPM", "LLY", "V", "MA", "XOM", "UNH", "HD", "PG", "JNJ", "COST", "WMT",
    "NFLX", "CRM", "ORCL", "CVX", "ABBV", "BAC", "KO", "PEP", "MRK", "TMO",
    "ACN", "CSCO", "MCD", "ABT", "DHR", "TXN", "QCOM", "AMGN", "IBM", "GE",
    "CAT", "BA", "GS", "MS", "DIS", "NKE", "INTC", "AMD", "MU", "BKNG",
]

NDX_40 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "COST",
    "NFLX", "AMD", "INTC", "CSCO", "QCOM", "TXN", "AMGN", "INTU", "ISRG",
    "BKNG", "ADBE", "ADI", "REGN", "VRTX", "MU", "LRCX", "AMAT", "KLAC",
    "SNPS", "CDNS", "CRWD", "PANW", "MAR", "ORLY", "CTAS", "PAYX", "ADP",
    "MELI", "ASML", "PEP", "SBUX",
]

INDEX_PROXIES = {"spx_liquid_50": SPX_LIQUID_50, "ndx_40": NDX_40}

# Refreshed universes (scripts/screening_universe_refresh.py, daily): real
# membership lists when the refresh has landed, the bundled liquid proxies
# until then. `sp500`/`nasdaq100`/`nasdaq_all` resolve through these.
REFRESHED = {"sp500": "spx_liquid_50", "nasdaq100": "ndx_40", "nasdaq_all": None}

UNIVERSE_BUILDERS = [
    {"name": "universe_list", "type": "list",
     "doc": "Explicit ticker list in the spec."},
    {"name": "universe_index_proxy", "type": "index_proxy",
     "doc": "Bundled liquid proxy for an index (spx_liquid_50, ndx_40); "
            "static curated lists, not licensed membership."},
    {"name": "universe_index", "type": "index",
     "doc": "Refreshed membership list (sp500, nasdaq100, nasdaq_all) from the "
            "daily universe refresh; falls back to the bundled liquid proxy "
            "(sp500/nasdaq100) until the first refresh lands."},
    {"name": "universe_sector", "type": "sector",
     "doc": "Sector cut of a base universe, via each name's yfinance sector."},
]


def resolve_universe(store, spec_universe: dict) -> list[str]:
    t = spec_universe.get("type")
    if t == "list":
        return sorted({str(x).upper() for x in spec_universe["tickers"]})
    if t == "index_proxy":
        idx = spec_universe["index"]
        if idx not in INDEX_PROXIES:
            raise ValueError(f"unknown index proxy '{idx}' "
                             f"(have: {', '.join(INDEX_PROXIES)})")
        return list(INDEX_PROXIES[idx])
    if t == "index":
        idx = spec_universe["index"]
        if idx not in REFRESHED:
            raise ValueError(f"unknown index '{idx}' (have: {', '.join(REFRESHED)})")
        fresh = _refreshed(idx)
        if fresh:
            return fresh
        fallback = REFRESHED[idx]
        if fallback is None:
            raise ValueError(f"index '{idx}' has no refreshed list yet and no bundled fallback; "
                             f"run the universe refresh first")
        return list(INDEX_PROXIES[fallback])
    if t == "sector":
        base = resolve_universe(store, spec_universe["base"])
        want = spec_universe["sector"].lower()
        return [x for x in base
                if (store.info(x).get("sector") or "").lower() == want]
    raise ValueError(f"unknown universe type '{t}'")
