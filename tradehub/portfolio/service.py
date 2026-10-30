"""The two portfolio payloads, assembled from the live paper account and the stored snapshots.

States, in the order a reader needs them:
- not_connected: no usable paper keys. 200 with no numbers, never a 500 and never zeros.
- stale: Alpaca did not answer; the last snapshot stands in, labelled with its own time.
- pre_start: a paper account answers, but it is not the account named in PORTFOLIO_ACCOUNT_NUMBER,
  so its numbers are a test account's, not the record's.
- live: the record's account, read just now.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from tradehub.portfolio import book
from tradehub.portfolio.alpaca_paper import AccountNotConnected, latest_spy_price, paper_get

SNAPSHOTS = "portfolio_snapshots"
FILL_PAGE = 100


def read_snapshots(supa, account_number: str | None) -> list[dict]:
    """Every snapshot for one account, oldest first. With no account, those of the latest account seen."""
    if supa is None:
        return []
    from tradehub.api.main import _fetch_all  # the shared ordered pager; imported late to avoid a cycle

    if account_number:
        return _fetch_all(supa, SNAPSHOTS, lambda q: q.select("*").eq("account_number", account_number),
                          order=("taken_at",))
    rows = _fetch_all(supa, SNAPSHOTS, lambda q: q.select("*"), order=("taken_at",))
    return [r for r in rows if r["account_number"] == rows[-1]["account_number"]] if rows else []


def _record_account() -> str:
    return os.getenv("PORTFOLIO_ACCOUNT_NUMBER", "").strip()


def _empty(state: str, as_of: str | None = None, account_number: str | None = None) -> dict:
    return {"state": state, "as_of": as_of, "account_number": account_number,
            "scoreboard": {**book.scoreboard([]), "win_rate": None}, "curve": [], "composition": [],
            "positions": []}


def _fills() -> list[dict]:
    fills: list[dict] = []
    params: dict = {"page_size": FILL_PAGE, "direction": "asc"}
    for _ in range(50):  # ponytail: 5,000 fills cap; page the closed-trades view if the book ever gets there
        page = paper_get("/v2/account/activities/FILL", params)
        fills.extend(page)
        if len(page) < FILL_PAGE:
            break
        params["page_token"] = page[-1]["id"]
    return fills


def portfolio(supa, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    try:
        account = paper_get("/v2/account")
        positions = paper_get("/v2/positions")
    except AccountNotConnected:
        return _empty("not_connected")
    except Exception:  # noqa: BLE001 -- Alpaca down or slow: fall back to the last snapshot, labelled stale
        snaps = read_snapshots(supa, _record_account() or None)
        if not snaps:
            return _empty("not_connected")
        out = _empty("stale", snaps[-1]["taken_at"], snaps[-1]["account_number"])
        out["scoreboard"] = {**book.scoreboard(snaps), "win_rate": None}
        out["curve"] = book.curve(snaps)
        return out

    number = account.get("account_number")
    snaps = read_snapshots(supa, number)
    try:
        snaps = snaps + [{"taken_at": now.isoformat(), "account_number": number,
                          "equity": float(account["equity"]), "cash": float(account["cash"]),
                          "spy_price": latest_spy_price()}]
    except Exception:  # noqa: BLE001 -- no SPY price: the curve ends at the last snapshot
        pass
    try:
        trades = book.closed_trades(_fills())
    except Exception:  # noqa: BLE001
        trades = None
    rows = book.positions_view(account, positions)
    score = book.scoreboard(snaps)
    score["equity"] = float(account["equity"])
    return {
        "state": "live" if number and number == _record_account() else "pre_start",
        "as_of": now.isoformat(),
        "account_number": number,
        "scoreboard": {**score, "win_rate": book.win_rate(trades) if trades is not None else None},
        "curve": book.curve(snaps),
        "composition": book.composition(rows),
        "positions": rows,
    }


def closed(now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    try:
        trades = book.closed_trades(_fills())
    except AccountNotConnected:
        return {"state": "not_connected", "as_of": None, "trades": []}
    except Exception:  # noqa: BLE001
        return {"state": "stale", "as_of": None, "trades": []}
    trades.sort(key=lambda t: t["exited_at"], reverse=True)
    return {"state": "live", "as_of": now.isoformat(), "trades": trades}


def take_snapshot(supa, now: datetime | None = None) -> dict | None:
    """Insert one snapshot of the paper account. None when there is no account to snapshot."""
    try:
        account = paper_get("/v2/account")
    except AccountNotConnected:
        return None
    row = {"taken_at": (now or datetime.now(UTC)).isoformat(), "account_number": account["account_number"],
           "equity": float(account["equity"]), "cash": float(account["cash"]), "spy_price": latest_spy_price()}
    supa.table(SNAPSHOTS).insert(row).execute()
    return row
