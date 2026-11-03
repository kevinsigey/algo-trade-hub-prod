"""Alpaca option contracts for the auto-trader (Kevin, 2026-11-02).

The Workshop spec's OptionLeg names an underlying, a kind, a side, a strike as a
percent of spot and a target expiry -- never a contract. This module is the bridge:
OCC symbol math, the chain read that picks the listed contract nearest the leg's
terms, and the latest-quote read an order is priced from. Quotes come from the data
API with the book's own keys; contracts from the paper host.

Pricing rule (Kevin's design): orders go in as DAY limits at the quote mid. A quote
that is missing, crossed, or wider than MAX_SPREAD_PCT of the mid is NOT tradable --
the planner turns that into a manual action instead of sending anything.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import requests

from tradehub.portfolio import alpaca_paper
from tradehub.portfolio.alpaca_paper import AccountNotConnected

MAX_SPREAD_PCT = 25.0  # (ask - bid) / mid above this -> not tradable, hand it to Kevin

_OCC = re.compile(r"^([A-Z]{1,6})\s*(\d{6})([CP])(\d{8})$")
_EQUITY = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def is_occ(symbol: str) -> bool:
    return bool(_OCC.match(symbol or ""))


def parse_occ(symbol: str) -> dict[str, Any]:
    m = _OCC.match(symbol or "")
    if not m:
        raise ValueError(f"not an OCC symbol: {symbol!r}")
    root, ymd, kind, strike = m.groups()
    return {"underlying": root, "expiry": date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:6])),
            "kind": "call" if kind == "C" else "put", "strike": int(strike) / 1000}


def build_occ(underlying: str, expiry: date, kind: str, strike: float) -> str:
    return (f"{underlying:<6}{expiry:%y%m%d}{'C' if kind == 'call' else 'P'}"
            f"{int(round(strike * 1000)):08d}")


def fetch_contracts(underlying: str, kind: str, target: date, *, book: str | None = None,
                    session=requests) -> list[dict]:
    """Listed, tradable contracts for one underlying+kind around the target expiry
    (+-21 days), from the paper host. Empty when the book is not connected."""
    params = {"underlying_symbols": underlying, "type": kind, "status": "active",
              "expiration_date_gte": (target - timedelta(days=21)).isoformat(),
              "expiration_date_lte": (target + timedelta(days=21)).isoformat(), "limit": 1000}
    out: list[dict] = []
    url: str | None = alpaca_paper.PAPER_BASE + "/v2/options/contracts"
    while url:
        response = session.get(url, headers=alpaca_paper._headers(book), params=params, timeout=15)
        if response.status_code == 401:
            raise AccountNotConnected("Alpaca rejected the keys (HTTP 401)")
        if response.status_code >= 400:
            return out
        body = response.json() or {}
        out.extend(c for c in body.get("option_contracts") or [] if c.get("tradable", True))
        url = body.get("next_page_token") and (alpaca_paper.PAPER_BASE + "/v2/options/contracts")
        params = {**params, "page_token": body.get("next_page_token")} if url else params
    return out


def select_contract(contracts: list[dict], leg, spot: float, today: date) -> str | None:
    """The contract nearest the leg's terms: expiry nearest today + days_to_expiry
    (ties to the later expiry), then the strike nearest spot * strike_pct."""
    if not contracts or spot <= 0:
        return None
    target_expiry = today + timedelta(days=leg.days_to_expiry)
    target_strike = spot * leg.strike_pct / 100

    def key(c: dict) -> tuple:
        expiry = date.fromisoformat(c["expiration_date"])
        return (abs((expiry - target_expiry).days), -(expiry - target_expiry).days,
                abs(float(c["strike_price"]) - target_strike))

    return min(contracts, key=key)["symbol"]


def fetch_mid(symbol: str, *, book: str | None = None, session=requests) -> float | None:
    """The latest quote's mid, or None when the quote is missing, crossed, or wider
    than MAX_SPREAD_PCT of the mid -- the planner's cue to hand the leg to Kevin."""
    response = session.get(alpaca_paper.DATA_BASE + "/v1beta1/options/quotes/latest",
                           headers=alpaca_paper._headers(book), params={"symbols": symbol}, timeout=10)
    if response.status_code == 401:
        raise AccountNotConnected("Alpaca rejected the keys (HTTP 401)")
    if response.status_code >= 400:
        return None
    quote = ((response.json() or {}).get("quotes") or {}).get(symbol) or {}
    bid, ask = float(quote.get("bp") or 0), float(quote.get("ap") or 0)
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2
    if mid <= 0 or (ask - bid) / mid * 100 > MAX_SPREAD_PCT:
        return None
    return round(mid, 2)
