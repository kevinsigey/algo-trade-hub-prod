"""Universe builders. A spec's `universe` is one of:
  {"type": "list", "tickers": [...]}                    explicit list
  {"type": "index_proxy", "index": "spx_liquid_50"}     bundled liquid proxies
  {"type": "index", "index": "sp500"}                   refreshed membership
  {"type": "index_union", "indexes": [...]}             union of refreshed lists
  {"type": "sector", "sector": "Technology",
   "base": <any universe object>}                      sector cut of a base
  {"type": "common_equity", "base": <any universe>}     common shares only

The index proxies are curated static lists of the most liquid constituents
(as of the Nov 2026 build) — labelled proxies, not licensed index membership.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def _cache_file(name: str) -> Path:
    return Path(os.environ.get("TRADEHUB_SCREENING_CACHE", "/cache/screening")) / name


def _refreshed(name: str) -> list[str] | None:
    """The daily-refreshed list for `name` from the screening cache, if present."""
    try:
        data = json.loads(_cache_file(f"universe_{name}.json").read_text())
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


_NAMES_CACHE: dict = {"key": None, "names": None}


def _refreshed_names() -> dict[str, str] | None:
    """Ticker -> exchange security name from the refresh's sidecar file
    (universe_names.json), if present. Cached per (path, mtime): a 13k-name
    universe resolves against one parse, not one file read per name."""
    f = _cache_file("universe_names.json")
    try:
        key = (str(f), f.stat().st_mtime_ns)
    except OSError:
        return None
    if _NAMES_CACHE["key"] != key:
        try:
            data = json.loads(f.read_text())
            names = {str(k).upper(): str(v) for k, v in (data.get("names") or {}).items()}
        except Exception:
            return None
        _NAMES_CACHE.update(key=key, names=names or None)
    return _NAMES_CACHE["names"]


# Non-common share classes, detected on the exchange security name (Kevin,
# 2026-11-09: Buffett's cohort was one issuer three times — ACGL plus its
# preferreds ACGLN/ACGLO). A coupon in the name ("5.45% ...") is never a
# common stock's name; the class words are the classes' own naming. The
# markers are deliberately contextual so a common whose name merely contains
# a word survives ("Preferred Bank" is a common; "United ..." is not units).
_NONCOMMON = re.compile(
    r"%"
    r"|\bpreferred\s+(shares|stock|series|securities)\b"
    r"|\bpreference\s+(shares|stock|series|securities)\b"
    r"|\b(senior|subordinated)\s+notes?\b"
    r"|\bnotes?\s+due\b"
    r"|\bunits\b"
    r"|\bwarrants?\b"
    r"|\brights\b",
    re.IGNORECASE)


def _security_name(store, ticker: str) -> str | None:
    names = _refreshed_names()
    if names and ticker in names:
        return names[ticker]
    info = getattr(store, "info", None)
    if callable(info):
        try:
            d = info(ticker) or {}
        except Exception:
            return None
        return d.get("longName") or d.get("shortName") or None
    return None


def is_common_equity(store, ticker: str) -> bool:
    """False only when the security name marks a non-common class. No name
    on record -> kept (an unjudgeable name is not evidence of a class)."""
    name = _security_name(store, ticker)
    if not name:
        return True
    return _NONCOMMON.search(name) is None


# A share-class tail in an exchange security name: "Alphabet Inc. - Class C
# Capital Stock", "Berkshire Hathaway Inc. - Class B Common Stock". Cutting
# at the CLASS/SERIES token collapses an issuer's share classes to one stem.
_CLASS_TAIL = re.compile(r"\b(?:CLASS|SERIES)\s+[A-Z]\b.*$", re.IGNORECASE)
_GENERIC_TAIL = re.compile(
    r"\s+(?:COMMON STOCK|CAPITAL STOCK|ORDINARY SHARES|COMMON SHARES)$", re.IGNORECASE)


def _issuer_stem(name: str | None, ticker: str) -> str:
    if not name:
        return ticker.upper()
    stem = _CLASS_TAIL.sub("", str(name))
    stem = re.sub(r"[^A-Za-z0-9]+", " ", stem).strip().upper()
    stem = _GENERIC_TAIL.sub("", stem).strip()
    return stem or ticker.upper()


def issuer_key(ticker: str, store=None) -> str:
    """One key per ISSUER for cohort counting and membership diffing.

    Dual-class names (GOOG/GOOGL) are two rows but one issuer; keying them
    apart double-counts the cohort and fabricates entrance/exit events when
    one class crosses a filter the other already passed. The key is the
    exchange security name with any CLASS/SERIES tail cut, so every share
    class of an issuer shares a stem. Names come from the refresh sidecar;
    a store, when passed, may fall back to its info record (the runner's
    footer path passes none -- no network for a count). Limits, stated:
    heuristic on names -- classes whose recorded names share no stem do not
    merge; a preferred line keeps its own key (its name carries no class
    token, and it is a different security, not a share class); a ticker
    with no recorded name is its own issuer, never merged blindly.
    """
    t = str(ticker).upper()
    names = _refreshed_names()
    name = names.get(t) if names else None
    if name is None and store is not None:
        name = _security_name(store, t)
    return _issuer_stem(name, t)

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
    {"name": "universe_index_union", "type": "index_union",
     "doc": "Union of refreshed index lists (e.g. sp500 + nasdaq100 = the "
            "large-cap US universe the nightly warm-up keeps warm)."},
    {"name": "universe_sector", "type": "sector",
     "doc": "Sector cut of a base universe, via each name's yfinance sector."},
    {"name": "universe_common_equity", "type": "common_equity",
     "doc": "Common-equity cut of a base universe: drops non-common classes "
            "(preferreds, units, warrants, rights, coupon notes) by the "
            "exchange security name — the refresh's names file first, the "
            "yfinance name as fallback. Equity screens screen common equity."},
]


def _resolve_index(idx: str) -> list[str]:
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
        return _resolve_index(spec_universe["index"])
    if t == "index_union":
        out: set[str] = set()
        for idx in spec_universe["indexes"]:
            out.update(_resolve_index(idx))
        return sorted(out)
    if t == "sector":
        base = resolve_universe(store, spec_universe["base"])
        want = spec_universe["sector"].lower()
        return [x for x in base
                if (store.info(x).get("sector") or "").lower() == want]
    if t == "common_equity":
        base = resolve_universe(store, spec_universe["base"])
        return [x for x in base if is_common_equity(store, x)]
    raise ValueError(f"unknown universe type '{t}'")
