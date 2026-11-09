"""Cron entrypoint: refresh the portfolio check's stored return series.

Weekly (Sunday, beside the ideas-shadow and ideas-critic jobs): for each book,
2y daily closes for every sleeve member and every held name become daily-return
series in portfolio_series -- one per sleeve, one per symbol, and '__book__'
(the book's own series). The portfolio check's correlation readout reads ONLY
these stored series: an order is never delayed by a price pull, and the card
and the gate read the same state, so they cannot disagree.

Weights are the refresh-time snapshot: a sleeve's series is its members'
returns weighted by their market-value share inside the sleeve (equal weights
when the book holds none of the sleeve yet), and the book's series is every
held name weighted by its share of invested. Stored series are history as
computed at each refresh; this is the cohesion method (2y daily closes),
frozen at refresh time rather than rebuilt per order.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.portfolio import books, portfolio_check
from tradehub.workshop.data import closes as workshop_closes

LOOKBACK_DAYS = 760  # ~2y of trading days plus listing gaps


def _returns_by_symbol(frame) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for symbol in frame.columns:
        series = frame[symbol].dropna()
        rets = series.pct_change().dropna()
        out[symbol] = {d.date().isoformat() if hasattr(d, "date") else str(d): float(r)
                       for d, r in rets.items()}
    return out


def _blend(weighted: list[tuple[dict[str, float], float]]) -> list:
    """Weight-blend return maps over their shared dates (a date missing any leg
    is dropped: a sleeve series never invents a day)."""
    if not weighted:
        return []
    total = sum(w for _, w in weighted)
    if total <= 0:
        return []
    shared = set(weighted[0][0])
    for rets, _ in weighted[1:]:
        shared &= set(rets)
    return [[d, round(sum(rets[d] * w for rets, w in weighted) / total, 6)]
            for d in sorted(shared)]


def build_series(positions: dict[str, dict], frame, config: dict) -> dict[str, list]:
    """positions: underlying -> {"mv"} (portfolio_check's read); frame: closes
    by symbol. Returns {series_key: [[day, ret], ...]} for every sleeve, every
    held or member symbol, and '__book__'."""
    rets = _returns_by_symbol(frame)
    mv = {s: float(p.get("mv") or 0.0) for s, p in positions.items() if not s.startswith("__")}
    invested = sum(mv.values())
    out: dict[str, list] = {}
    for symbol, r in rets.items():
        out[f"sym:{symbol}"] = [[d, round(v, 6)] for d, v in sorted(r.items())]
    for sleeve_id, sleeve in config["sleeves"].items():
        members = [s for s in sleeve.get("symbols", []) if s in rets]
        if not members:
            continue
        held = [(rets[s], mv[s]) for s in members if mv.get(s)]
        legs = held if held else [(rets[s], 1.0) for s in members]
        out[sleeve_id] = _blend(legs)
    if invested > 0:
        out["__book__"] = _blend([(rets[s], mv[s]) for s in mv if s in rets and mv[s] != 0])
    return out


def refresh_book(supa, book: str, *, closes_fn=workshop_closes, today: date | None = None) -> dict:
    config = portfolio_check.load_config(supa)
    positions = portfolio_check.positions_by_underlying(book)
    held = [s for s in positions if not s.startswith("__")]
    members = sorted({s for sleeve in config["sleeves"].values() for s in sleeve.get("symbols", [])})
    tickers = sorted(set(members) | set(held))
    start = (today or date.today()) - timedelta(days=LOOKBACK_DAYS)
    frame = closes_fn(tickers, start)
    series = build_series(positions, frame, config)
    for key, days in series.items():
        supa.table(portfolio_check.SERIES_TABLE).upsert(
            {"book": book, "series_key": key, "days": days}).execute()
    return {"book": book, "series": len(series),
            "days": len(series.get("__book__", []))}


def main(supa=None) -> int:
    load_local_env()
    client = supa or get_client()
    out: dict = {}
    code = 0
    for name in books.names():
        try:
            out[name] = refresh_book(client, name)
        except Exception as exc:  # noqa: BLE001 -- one book failing never stops the other
            out[name] = {"series": "failed", "error": f"{type(exc).__name__}: {exc}"}
            code = 1
    print(json.dumps(out))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
