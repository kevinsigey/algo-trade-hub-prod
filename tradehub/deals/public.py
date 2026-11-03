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
