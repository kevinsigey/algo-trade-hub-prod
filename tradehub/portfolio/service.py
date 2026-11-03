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
import re
from datetime import UTC, datetime

from tradehub.portfolio import book
from tradehub.portfolio.alpaca_paper import AccountNotConnected, latest_spy_price, paper_get
from tradehub.workshop import store as workshop_store

SNAPSHOTS = "portfolio_snapshots"


def _with_book(fn):
    """Run a payload builder inside its book's context: the Alpaca reads below resolve
    the book from the context variable (tradehub.portfolio.books), so the two accounts'
    payloads never cross and existing call shapes stay (path, params)."""

    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from tradehub.portfolio.books import reset_book, use_book

        token = use_book(kwargs.get("book_name"))
        try:
            return fn(*args, **kwargs)
        finally:
            reset_book(token)

    return wrapper
FILL_PAGE = 100
ORDER_PAGE = 500


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


def _record_account(book_name: str | None = None) -> str:
    """The account number that counts as the record for a book. The main book's is pinned by
    env (a different account answering reads pre_start, a test account's numbers). The $1M
    book's pin is optional: unset, whatever account its keys reach IS its record."""
    from tradehub.portfolio.books import resolve

    env = "PORTFOLIO_ACCOUNT_NUMBER" if resolve(book_name) == "main" else "PORTFOLIO_ACCOUNT_NUMBER_BIG"
    return os.getenv(env, "").strip()


def _empty(state: str, as_of: str | None = None, account_number: str | None = None) -> dict:
    return {"state": state, "as_of": as_of, "account_number": account_number,
            "scoreboard": {**book.scoreboard([]), "win_rate": None}, "curve": [], "composition": [],
            "positions": []}


def _fills(book_name: str | None = None) -> list[dict]:
    fills: list[dict] = []
    params: dict = {"page_size": FILL_PAGE, "direction": "asc"}
    for _ in range(50):  # ponytail: 5,000 fills cap; page the closed-trades view if the book ever gets there
        page = paper_get("/v2/account/activities/FILL", params)
        fills.extend(page)
        if len(page) < FILL_PAGE:
            break
        params["page_token"] = page[-1]["id"]
    return fills


def _orders(book_name: str | None = None) -> dict[str, str]:
    """order id -> client_order_id, for every order on the paper account (GET only)."""
    out: dict[str, str] = {}
    params: dict = {"status": "all", "direction": "asc", "limit": ORDER_PAGE, "nested": "true"}
    for _ in range(20):  # ponytail: 10,000 orders cap
        page = paper_get("/v2/orders", params)
        for o in page:
            out[o["id"]] = o.get("client_order_id") or ""
            for leg in o.get("legs") or []:  # one-cancels-other halves fill under the parent's tag
                out[leg["id"]] = out[o["id"]]
        if len(page) < ORDER_PAGE:
            break
        params = {**params, "after": page[-1]["submitted_at"]}
    return out


def _titles(supa, public: bool) -> dict[int, str]:
    rows = supa.table("ideas").select("id,title,published_at").execute().data
    return {r["id"]: r["title"] for r in rows if r.get("published_at") or not public}


@_with_book
def tagged_fills(supa, public: bool = True, book_name: str | None = None) -> tuple[list[dict], dict[str, str]]:
    """Fills with their idea. Public views name published ideas only; anything else reads as manual."""
    fills = _fills(book_name)
    try:
        client_ids = _orders(book_name)
    except AccountNotConnected:
        raise
    except Exception:  # noqa: BLE001 -- no order map: fills stay unattributed rather than the page failing
        client_ids = {}
    try:
        labels, titles = workshop_store.labels(supa), _titles(supa, public)
    except Exception:  # noqa: BLE001
        labels, titles = {}, {}
    return book.tag_fills(fills, client_ids, labels, titles), client_ids


@_with_book
def portfolio(supa, now: datetime | None = None, book_name: str | None = None) -> dict:
    from tradehub.portfolio.books import resolve

    name = resolve(book_name)
    now = now or datetime.now(UTC)
    try:
        account = paper_get("/v2/account")
        positions = paper_get("/v2/positions")
    except AccountNotConnected:
        return {**_empty("not_connected"), "book": name}
    except Exception:  # noqa: BLE001 -- Alpaca down or slow: fall back to the last snapshot, labelled stale
        snaps = read_snapshots(supa, _record_account(name) or None)
        if not snaps:
            return _empty("not_connected")
        out = _empty("stale", snaps[-1]["taken_at"], snaps[-1]["account_number"])
        out["scoreboard"] = {**book.scoreboard(snaps), "win_rate": None}
        out["curve"] = book.curve(snaps)
        out["book"] = name
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
        fills = tagged_fills(supa, book_name=name)[0]
        trades, lots = book.closed_trades(fills), book.open_lots(fills)
    except Exception:  # noqa: BLE001
        trades, lots = None, None
    rows = book.positions_view(account, positions, lots)
    score = book.scoreboard(snaps)
    score["equity"] = float(account["equity"])
    record = _record_account(name)
    return {
        "book": name,
        "state": "live" if number and (number == record or (not record and name != "main")) else "pre_start",
        "as_of": now.isoformat(),
        "account_number": number,
        "scoreboard": {**score, "win_rate": book.win_rate(trades) if trades is not None else None},
        "curve": book.curve(snaps),
        "composition": book.composition(rows),
        "positions": rows,
    }


_TERMINAL = {"filled", "canceled", "expired", "rejected", "replaced"}
_IDEA_TAG = re.compile(r"^idea-(\d+)-")
_OPTION_SYMBOL = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


def _order_source(client_order_id: str, titles: dict[int, str]) -> str:
    m = _IDEA_TAG.match(client_order_id or "")
    if m:
        return titles.get(int(m.group(1)), "Workshop idea")
    if (client_order_id or "").startswith("ext-"):
        return "Machine order"
    return "Manual"


def _order_row(o: dict, titles: dict[int, str]) -> dict:
    def num(key):
        v = o.get(key)
        return float(v) if v not in (None, "") else None
    return {"symbol": o.get("symbol"), "side": o.get("side"), "qty": num("qty"),
            "filled_qty": num("filled_qty"), "type": o.get("type") or o.get("order_type"),
            "time_in_force": o.get("time_in_force"), "status": o.get("status"),
            "limit_price": num("limit_price"), "stop_price": num("stop_price"),
            "filled_avg_price": num("filled_avg_price"),
            "submitted_at": o.get("submitted_at"), "filled_at": o.get("filled_at"),
            "asset": "option" if _OPTION_SYMBOL.match(o.get("symbol") or "") else "stock",
            "source": _order_source(o.get("client_order_id") or "", titles)}


@_with_book
def activity(supa, now: datetime | None = None, book_name: str | None = None) -> dict:
    """The Trades and Orders page payload: working orders, the recent order tape, and
    closed trades. The page carried only closed trades until 2026-11-02, so with no
    exits yet it rendered empty despite a book full of resting and filled orders."""
    now = now or datetime.now(UTC)
    from tradehub.portfolio.books import resolve

    name = resolve(book_name)
    empty = {"state": "not_connected", "as_of": None, "book": name, "open": [], "recent": [], "trades": []}
    try:
        orders = paper_get("/v2/orders", {"status": "all", "direction": "desc", "limit": 500})
    except AccountNotConnected:
        return empty
    except Exception:  # noqa: BLE001 -- same contract as closed(): never a 500 for a down feed
        return {**empty, "state": "stale"}
    try:
        titles = _titles(supa, public=True)
    except Exception:  # noqa: BLE001 -- attribution is decoration; the tape still reads
        titles = {}
    rows = [_order_row(o, titles) for o in orders]
    return {"state": "live", "as_of": now.isoformat(), "book": name,
            "open": [r for r in rows if r["status"] not in _TERMINAL],
            "recent": rows[:50],
            "trades": closed(supa, now, book_name=name)["trades"]}


@_with_book
def closed(supa, now: datetime | None = None, book_name: str | None = None) -> dict:
    from tradehub.portfolio.books import resolve

    name = resolve(book_name)
    now = now or datetime.now(UTC)
    try:
        trades = book.closed_trades(tagged_fills(supa, book_name=name)[0])
    except AccountNotConnected:
        return {"state": "not_connected", "as_of": None, "book": name, "trades": []}
    except Exception:  # noqa: BLE001
        return {"state": "stale", "as_of": None, "book": name, "trades": []}
    trades.sort(key=lambda t: t["exited_at"], reverse=True)
    return {"state": "live", "as_of": now.isoformat(), "book": name, "trades": trades}


@_with_book
def take_snapshot(supa, now: datetime | None = None, book_name: str | None = None) -> dict | None:
    """Insert one snapshot of the paper account. None when there is no account to snapshot."""
    from tradehub.portfolio.books import resolve

    name = resolve(book_name)
    try:
        account = paper_get("/v2/account")
    except AccountNotConnected:
        return None
    row = {"taken_at": (now or datetime.now(UTC)).isoformat(), "account_number": account["account_number"],
           "equity": float(account["equity"]), "cash": float(account["cash"]),
           "spy_price": latest_spy_price()}
    supa.table(SNAPSHOTS).insert(row).execute()
    return row
