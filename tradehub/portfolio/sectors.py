"""Curated ticker -> sector map for the Portfolio composition view.

Hand-kept, deliberately: the account trades a small universe (sector ETFs,
index funds, mega-cap names, the lab's ballast), and a wrong-but-plausible
auto-classification is worse than an honest "Other". A ticker not listed
here reads "Other" on the page, which is the prompt to add it here -- one
obvious place, no second map. Sector ETFs map to the sector they track.
"""

from __future__ import annotations

SECTOR_BY_SYMBOL: dict[str, str] = {
    # Sector ETFs (SPDR suite and the common trackers)
    "XLE": "Energy", "XOP": "Energy",
    "XLV": "Health Care", "XBI": "Health Care", "IBB": "Health Care",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLF": "Financials", "KRE": "Financials",
    "XLK": "Technology", "SMH": "Technology", "SOXX": "Technology",
    "XLY": "Consumer Discretionary", "XHB": "Consumer Discretionary", "XRT": "Consumer Discretionary",
    "XLB": "Materials", "XME": "Materials",
    "XLI": "Industrials", "ITA": "Industrials", "XAR": "Industrials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
    # Broad market / index funds
    "SPY": "Broad Market", "VOO": "Broad Market", "IVV": "Broad Market",
    "QQQ": "Broad Market", "DIA": "Broad Market", "IWM": "Broad Market",
    # Commodities and bonds (the lab's ballast shelf)
    "GLD": "Commodities (Gold)", "SLV": "Commodities (Silver)",
    "USO": "Commodities (Oil)", "DBC": "Commodities", "GDX": "Materials",
    "BND": "Bonds", "AGG": "Bonds", "TLT": "Bonds", "IEF": "Bonds",
    "SHY": "Bonds", "LQD": "Bonds", "HYG": "Bonds",
    "VNQ": "Real Estate",
    # Single names the account holds or the lab trades
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AVGO": "Technology", "AMD": "Technology", "INTC": "Technology",
    "TXN": "Technology", "MU": "Technology", "TSM": "Technology",
    "MRVL": "Technology",
    "IBIT": "Crypto", "EEM": "International",
    "TWLO": "Technology", "CRM": "Technology", "ORCL": "Technology",
    "ADBE": "Technology", "NOW": "Technology", "PLTR": "Technology",
    "ASML": "Technology",
    "META": "Communication Services", "GOOGL": "Communication Services",
    "GOOG": "Communication Services", "NFLX": "Communication Services",
    "DIS": "Communication Services", "T": "Communication Services",
    "VZ": "Communication Services",
    "MA": "Financials", "V": "Financials", "JPM": "Financials",
    "BAC": "Financials", "WFC": "Financials", "GS": "Financials",
    "MS": "Financials", "AXP": "Financials",
    "BRK/B": "Financials", "BRK.B": "Financials",
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "OXY": "Energy",
    "SLB": "Energy", "EOG": "Energy", "MPC": "Energy", "PSX": "Energy",
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    "RL": "Consumer Discretionary", "WSM": "Consumer Discretionary",
    "WMT": "Consumer Staples", "COST": "Consumer Staples",
    "PG": "Consumer Staples", "KO": "Consumer Staples",
    "PEP": "Consumer Staples", "MO": "Consumer Staples",
    "DLTR": "Consumer Staples", "DG": "Consumer Staples", "BJ": "Consumer Staples",
    "LLY": "Health Care", "UNH": "Health Care", "JNJ": "Health Care",
    "ABBV": "Health Care", "MRK": "Health Care",
    "PLD": "Real Estate",
    "CAT": "Industrials", "BA": "Industrials", "HON": "Industrials",
    "UPS": "Industrials",
}


def sector_for(symbol: str | None) -> str:
    """The sector one position reads as. Cash is its own bucket; unmapped is "Other"."""
    sym = (symbol or "").strip().upper()
    if sym == "CASH":
        return "Cash"
    return SECTOR_BY_SYMBOL.get(sym, "Other")


def idea_sector(symbols: list[str]) -> str:
    """The sector an idea's bet is in: the one most of its names share (Kevin, 2026-11-05, grouping the
    Ideas page). A broad-market core never names the bet unless it is all there is; ties go to the first
    name, so the spec's order decides."""
    sectors = [sector_for(s) for s in symbols]
    named = [s for s in sectors if s not in ("Broad Market", "Other")] or sectors
    if not named:
        return "Other"
    return max(dict.fromkeys(named), key=named.count)
