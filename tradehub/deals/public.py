"""Public-company prefill for the M&A builder: price and filed scale from
Yahoo Finance (the same free source the screening layer uses), stamped with
its as-of. Multiples default to the company's own current EV multiples
+/-15% -- a derived starting point the form labels as such, never a comp
set."""

from __future__ import annotations

from datetime import datetime, timezone

import yfinance as yf


def public_company(ticker: str) -> dict:
    info = yf.Ticker(ticker).info or {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    shares = info.get("sharesOutstanding")
    if not price or not shares:
        raise ValueError(f"no public data for {ticker}")
    revenue = (info.get("totalRevenue") or 0) / 1e9
    ebitda = (info.get("ebitda") or 0) / 1e9
    net_cash = ((info.get("totalCash") or 0) - (info.get("totalDebt") or 0)) / 1e9
    ev = price * shares / 1e9 + (info.get("totalDebt") or 0) / 1e9 - (info.get("totalCash") or 0) / 1e9
    out = {"name": info.get("shortName") or ticker, "ticker": ticker, "price": round(float(price), 2),
           "shares_b": round(shares / 1e9, 4),
           "revenue_b": round(revenue, 2) if revenue else None,
           "ebitda_b": round(ebitda, 2) if ebitda else None,
           "eps": info.get("trailingEps"), "net_cash_b": round(net_cash, 2),
           "source": "Yahoo Finance", "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if revenue:
        m = ev / revenue
        out["rev_multiples"] = {"low": round(m * 0.85, 2), "high": round(m * 1.15, 2)}
    if ebitda:
        m = ev / ebitda
        out["ebitda_multiples"] = {"low": round(m * 0.85, 2), "high": round(m * 1.15, 2)}
    return out


# ---------------------------------------------------------------------------
# Filed (EDGAR) prefill: the company's latest 10-K numbers parsed from XBRL
# company facts -- Kevin's ask (Nov 2): ask for the latest filed information
# and parse it ourselves. Price still comes from the market (filings carry
# none); every filed figure carries its filing date. EBITDA is not an XBRL
# concept: operating income stands in and the source line says so.

import requests

_UA = {"User-Agent": "algo-trade-hub sigeykevin@gmail.com"}
_cik_cache: dict[str, str] = {}


def _cik(ticker: str, get=requests.get) -> str:
    if ticker not in _cik_cache:
        data = get("https://www.sec.gov/files/company_tickers.json", headers=_UA, timeout=30).json()
        _cik_cache.update({row["ticker"].upper(): str(row["cik_str"]).zfill(10) for row in data.values()})
    if ticker not in _cik_cache:
        raise ValueError(f"{ticker}: not found in EDGAR's ticker map")
    return _cik_cache[ticker]


def _concept(cik: str, taxonomy: str, names: list[str], get=requests.get) -> tuple[float, str] | None:
    """Latest fiscal-year (10-K) value for the first concept that has one:
    (value, filed date)."""
    for name in names:
        try:
            payload = get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/{taxonomy}/{name}.json",
                          headers=_UA, timeout=30).json()
        except Exception:  # noqa: BLE001 -- a missing concept 404s; try the next
            continue
        units = payload.get("units") or {}
        rows = next(iter(units.values()), [])
        fy = [r for r in rows if str(r.get("form", "")).startswith("10-K") and r.get("val") is not None]
        if not fy:
            fy = [r for r in rows if r.get("val") is not None]
        if fy:
            best = max(fy, key=lambda r: (str(r.get("end", "")), str(r.get("filed", ""))))
            return float(best["val"]), str(best.get("filed", ""))
    return None


def edgar_company(ticker: str, *, get=requests.get) -> dict:
    cik = _cik(ticker.upper(), get)
    rev = _concept(cik, "us-gaap", ["RevenueFromContractWithCustomerExcludingAssessedTax",
                                    "Revenues", "SalesRevenueNet"], get)
    if rev is None:
        raise ValueError(f"{ticker}: no revenue concept in its EDGAR filings")
    op_inc = _concept(cik, "us-gaap", ["OperatingIncomeLoss"], get)
    cash = _concept(cik, "us-gaap", ["CashAndCashEquivalentsAtCarryingValue"], get)
    debt = _concept(cik, "us-gaap", ["DebtLongtermAndShorttermCombinedAmount", "LongTermDebt"], get)
    shares = _concept(cik, "dei", ["EntityCommonStockSharesOutstanding"], get) or \
        _concept(cik, "us-gaap", ["CommonStockSharesOutstanding",
                                  "WeightedAverageNumberOfDilutedSharesOutstanding"], get)
    eps = _concept(cik, "us-gaap", ["EarningsPerShareDiluted"], get)
    info = {}
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:  # noqa: BLE001 -- price is a courtesy here, not the point
        info = {}
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    filed = rev[1]
    out = {"name": info.get("shortName") or ticker, "ticker": ticker.upper(),
           "price": round(float(price), 2) if price else None,
           "shares_b": round(shares[0] / 1e9, 4) if shares else None,
           "revenue_b": round(rev[0] / 1e9, 2),
           "ebitda_b": round(op_inc[0] / 1e9, 2) if op_inc else None,
           "ebitda_basis": "operating income (EDGAR has no EBITDA concept)" if op_inc else None,
           "eps": round(eps[0], 2) if eps else None,
           "net_cash_b": (round((cash[0] - (debt[0] if debt else 0)) / 1e9, 2) if cash else None),
           "source": "SEC EDGAR (filed 10-K) + Yahoo price",
           "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "filing_as_of": filed}
    if price and out["shares_b"]:
        ev = float(price) * out["shares_b"] - (out["net_cash_b"] or 0)
        m = ev / out["revenue_b"]
        out["rev_multiples"] = {"low": round(m * 0.85, 2), "high": round(m * 1.15, 2)}
        if out["ebitda_b"]:
            m2 = ev / out["ebitda_b"]
            out["ebitda_multiples"] = {"low": round(m2 * 0.85, 2), "high": round(m2 * 1.15, 2)}
    return out
