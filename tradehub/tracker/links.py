"""trade_links: the join between a placed order and the forecast that
authorized it (design PR 5). Written at placement by the machine order
route — one row per placed client_order_id (a split parent writes one
per child), idempotent on the id. P&L is never stored here: it is read
from the book.py FIFO by client_order_id (closed trades now carry the
opening order's client id; open lots expose theirs), net of the
ledger's own math — option round trips at the x100 contract
multiplier, as fixed in PR #543.

Claim C reads its fire nets here: play-kind-(a) links in placement
order, each fire's net counted only once the fire is FULLY closed
AND its entry order is terminal (a partly-filled entry whose filled
part already closed can still take more fills), and the walk stops
at the first incomplete fire — the frozen window
is the NEXT five fires, so a later fire may not jump an earlier one
that is still open. A link that produced no position at all (the
order never filled) is skipped once it is older than the pending
window; younger than that it still blocks the walk, because its fills
may simply not have landed yet.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

LINKS = "trade_links"
PENDING_DAYS = 7


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(
            tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def record_link(client, *, client_order_id: str, book: str,
                play_kind: str, modal_value, opposing_case_ref,
                forecast_id=None, thesis_id=None,
                shadow: bool = False) -> dict:
    """Insert the link for one placed order; a retry of the same
    placement returns the row already written (the table's unique
    client_order_id is the idempotency key). A row recorded on
    DIFFERENT terms (a shadow record vs a live order, or another play
    kind) is a conflict, not a retry — the same caller id reused for a
    different thing — and raises."""
    def fetch():
        return (client.table(LINKS).select("*")
                .eq("client_order_id", client_order_id)
                .execute().data) or []

    def check_terms(row):
        if bool(row.get("shadow")) != bool(shadow) \
                or row.get("play_kind") != play_kind:
            raise ValueError(
                f"client_order_id {client_order_id} is already recorded "
                "with different link terms (shadow/play_kind)")

    rows = fetch()
    if rows:
        check_terms(rows[0])
        return rows[0]
    row = {"client_order_id": client_order_id, "book": book,
           "forecast_id": forecast_id, "thesis_id": thesis_id,
           "play_kind": play_kind, "modal_value": modal_value,
           "opposing_case_ref": opposing_case_ref,
           "shadow": bool(shadow)}
    try:
        inserted = (client.table(LINKS).insert(row).execute().data) or []
    except Exception:
        # A concurrent call stored the same id between the check and
        # the insert (the column is unique): its row is the record.
        stored = fetch()
        if not stored:
            raise
        check_terms(stored[0])
        return stored[0]
    return inserted[0] if inserted else row


def resolve_thesis(client, *, forecast_id=None, thesis_id=None):
    """(thesis_id, error) — validate the order's tracker references
    against the ledger. A forecast card's thesis fills in when the
    order names the card but not the thesis; a reference that names
    nothing real is an error, never a trusted claim."""
    if forecast_id is not None:
        rows = (client.table("forecast_cards").select("id, thesis_id")
                .eq("id", forecast_id).execute().data) or []
        if not rows:
            return None, f"forecast_id {forecast_id} names no forecast card"
        if thesis_id is None:
            thesis_id = rows[0].get("thesis_id")
    if thesis_id is not None:
        rows = (client.table("theses").select("id")
                .eq("id", thesis_id).execute().data) or []
        if not rows:
            return None, f"thesis_id {thesis_id} names no thesis"
    return thesis_id, None


def all_links(client) -> list[dict]:
    rows = (client.table(LINKS).select("*")
            .order("created_at").execute().data) or []
    return sorted(rows, key=lambda r: (str(r.get("created_at") or ""),
                                       r.get("id") or 0))


def _book_view(book_state: dict, book: str) -> tuple[list[dict], set, set]:
    """(closed trades, open-lot client_order_ids, non-terminal-order
    client_order_ids) for one book the caller DID read (an unreadable
    book is absent from book_state, and the fire walk stops at its
    first link rather than guessing)."""
    view = book_state.get(book) or {}
    return (view.get("closed") or [], view.get("open_client_ids") or set(),
            view.get("open_order_ids") or set())


def claim_c_fire_nets(client, book_state: dict, *,
                      now: datetime | None = None,
                      pending_days: int = PENDING_DAYS) -> list[float]:
    """The play-kind-(a) fire nets in fire order, per the module
    docstring's queue rule. `book_state` maps book -> {closed: [trade
    rows carrying client_order_id + pnl], open_client_ids: set} — the
    grade run builds it from the FIFO; tests inject it."""
    now = now or datetime.now(timezone.utc)
    nets: list[float] = []
    for link in all_links(client):
        if link.get("play_kind") != "a" or link.get("shadow"):
            continue
        if link["book"] not in book_state:
            break  # the book could not be read: undecidable, stop here
        closed, open_ids, open_orders = _book_view(book_state,
                                                   link["book"])
        cid = link["client_order_id"]
        trades = [t for t in closed if t.get("client_order_id") == cid]
        if cid in open_orders:
            break  # the entry order is not terminal (e.g. partly
            # filled, the filled part already closed): more fills can
            # still land and change this fire's net — it is not final
        if cid in open_ids:
            break  # still open: this fire has no net yet, and it is next
        if trades:
            nets.append(round(sum(float(t.get("pnl") or 0)
                                  for t in trades), 2))
            continue
        created = _parse(link.get("created_at"))
        if created is not None and now - created > timedelta(
                days=pending_days):
            continue  # never filled: no position ever resulted
        break  # too young to call: its fills may not have landed
    return nets


def pnl_by_play_kind(client, book_state: dict) -> dict:
    """Realized P&L per play kind from the FIFO, net of the ledger's
    math: {kind: {links, trades, wins, pnl}} over non-shadow links
    that have closed trades (a partially closed fire contributes what
    has realized so far). The scoreboard (PR 7) renders this — wins
    are the closed trades with pnl > 0, its hit-rate numerator; the
    kinds are reported separately, never blended."""
    out: dict[str, dict] = {}
    for link in all_links(client):
        if link.get("shadow"):
            continue
        closed, _, _ = _book_view(book_state, link["book"])
        trades = [t for t in closed
                  if t.get("client_order_id") == link["client_order_id"]]
        if not trades:
            continue
        slot = out.setdefault(link["play_kind"],
                              {"links": 0, "trades": 0, "wins": 0,
                               "pnl": 0.0})
        slot["links"] += 1
        slot["trades"] += len(trades)
        slot["wins"] += sum(1 for t in trades
                            if float(t.get("pnl") or 0) > 0)
        slot["pnl"] = round(slot["pnl"] + sum(
            float(t.get("pnl") or 0) for t in trades), 2)
    return out
