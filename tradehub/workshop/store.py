"""Ideas, their runs, shadow days and order labels in Supabase.

Runs, shadow days and labels are insert-only (DB triggers). An idea's published/live/killed timestamps are set once:
the update only matches while the column is still null, and the DB trigger refuses any later change.
"""

from __future__ import annotations

from datetime import UTC, datetime

IDEAS, RUNS, SHADOW, LABELS = "ideas", "idea_runs", "idea_shadow_days", "order_labels"
CRITIQUES = "idea_critiques"
SAVES = "idea_run_saves"
SWITCHES, ORDERS = "order_switches", "paper_orders"
ACTIVATIONS = "book_activations"


class AlreadySet(Exception):
    """The lifecycle step already happened (or the idea does not exist); nothing changed."""


def _set_once(supa, idea_id: int, column: str, extra: dict | None = None) -> dict:
    patch = {column: datetime.now(UTC).isoformat(), **(extra or {})}
    rows = supa.table(IDEAS).update(patch).eq("id", idea_id).is_(column, "null").execute().data
    if not rows:
        raise AlreadySet(column)
    return rows[0]


def publish(supa, idea_id: int) -> dict:
    return _set_once(supa, idea_id, "published_at")


def go_live(supa, idea_id: int, run_id: int, size_pct: float, gate: dict) -> dict:
    return _set_once(supa, idea_id, "live_at", {"live_run_id": run_id, "size_pct": size_pct, "gate": gate})


def track(supa, idea_id: int, run_id: int) -> dict:
    """Start the forward shadow record for a passed run. No orders, no gate: tracking is
    observation, and it is set once like every other lifecycle step."""
    return _set_once(supa, idea_id, "tracked_at", {"tracked_run_id": run_id})


def kill(supa, idea_id: int) -> dict:
    return _set_once(supa, idea_id, "killed_at", {"auto_orders": False})  # a killed idea never trades again


def _all_ideas(supa) -> list[dict]:
    # ponytail: whole-table read; filter in SQL if ideas ever number in the thousands
    return supa.table(IDEAS).select("*").order("created_at", desc=True).execute().data


def live_ideas(supa) -> list[dict]:
    return [i for i in _all_ideas(supa) if i.get("live_at") and not i.get("killed_at")]


def tracked_ideas(supa) -> list[dict]:
    """Tracked but not yet live: the shadow job records these from tracked_at. Once an idea
    goes live it leaves this set -- the live anchor takes over the same record."""
    return [i for i in _all_ideas(supa)
            if i.get("tracked_at") and not i.get("live_at") and not i.get("killed_at")]


def published_ideas(supa) -> list[dict]:
    return [i for i in _all_ideas(supa) if i.get("published_at")]


def shadow_days(supa, idea_id: int) -> list[dict]:
    return supa.table(SHADOW).select("*").eq("idea_id", idea_id).order("day").execute().data


def append_shadow(supa, idea_id: int, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    return supa.table(SHADOW).insert([{"idea_id": idea_id, **r} for r in rows]).execute().data


def add_label(supa, order_id: str, idea_id: int | None, by: str, tag: str | None = None,
              reason: str | None = None) -> dict:
    row = {"order_id": order_id, "idea_id": idea_id, "by": by}
    if tag is not None:
        row["tag"] = tag  # the thesis tag (2026-11-08): metadata only, nothing routes by it
    if reason is not None:
        # The stated reason (2026-11-11): why a discretionary machine order
        # exists. Stored only when stated, so rows written before the
        # order_labels.reason migration simply carry no key.
        row["reason"] = reason
    return supa.table(LABELS).insert(row).execute().data[0]


def add_manual_move(supa, book: str, symbol: str, idea_id: int, by: str) -> dict:
    return supa.table("manual_moves").insert({"book": book, "symbol": symbol, "idea_id": idea_id, "by": by,
                                              "at": datetime.now(UTC).isoformat()}).execute().data[0]


def manual_moves(supa, book: str) -> dict[str, tuple[int, str]]:
    """Symbol -> (idea id that takes this book's manual shares of it, when); the latest move wins.
    ponytail: one read, no paging; a move is a rare hand-made row, nowhere near the 1,000-row page."""
    return {r["symbol"]: (r["idea_id"], r["at"])
            for r in supa.table("manual_moves").select("*").eq("book", book).order("id").execute().data}


def label_history(supa) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in supa.table(LABELS).select("*").order("id").execute().data:
        out.setdefault(r["order_id"], []).append(r)
    return out


def labels(supa) -> dict[str, int | None]:
    """The current label per order id: the latest relabel wins."""
    return {order: rows[-1]["idea_id"] for order, rows in label_history(supa).items()}


def label_tags(supa) -> dict[str, str]:
    """Order id -> its thesis tag, for the orders that carry one (latest row wins)."""
    return {order: rows[-1]["tag"] for order, rows in label_history(supa).items()
            if rows[-1].get("tag")}


def label_reasons(supa) -> dict[str, str]:
    """Order id -> its stated reason, for the orders that carry one (latest row wins)."""
    return {order: rows[-1]["reason"] for order, rows in label_history(supa).items()
            if rows[-1].get("reason")}


def create_idea(supa, title: str, plain_words: str) -> dict:
    return supa.table(IDEAS).insert({"title": title, "plain_words": plain_words}).execute().data[0]


def get_idea(supa, idea_id: int) -> dict | None:
    rows = supa.table(IDEAS).select("*").eq("id", idea_id).execute().data
    if not rows:
        return None
    runs = supa.table(RUNS).select("*").eq("idea_id", idea_id).order("variation").execute().data
    return {"idea": rows[0], "runs": _annotate_saved(supa, runs)}


def list_ideas(supa) -> list[dict]:
    ideas = supa.table(IDEAS).select("*").order("created_at", desc=True).execute().data
    runs = supa.table(RUNS).select("id,idea_id,variation,verdict").execute().data
    # The list speaks for the record, so it reads saved runs only: a preview does
    # not change an idea's standing until it is saved (save-by-choice, 2026-11-02).
    saved_ids = {s["run_id"] for s in supa.table(SAVES).select("run_id").execute().data}
    latest: dict[int, tuple[int, str]] = {}
    for r in runs:
        if r["id"] not in saved_ids:
            continue
        if r["variation"] > latest.get(r["idea_id"], (0, ""))[0]:
            latest[r["idea_id"]] = (r["variation"], r["verdict"])
    return [{"id": i["id"], "title": i["title"], "created_at": i["created_at"],
             "runs": latest.get(i["id"], (0, None))[0], "latest_verdict": latest.get(i["id"], (0, None))[1],
             "published_at": i.get("published_at"), "tracked_at": i.get("tracked_at"),
             "live_at": i.get("live_at"), "killed_at": i.get("killed_at")}
            for i in ideas]


def insert_run(supa, idea_id: int, variation: int, spec: dict, draft_model: str | None, result: dict) -> dict:
    # The hub-wide registry position (Kevin, 2026-11-03): this run is the
    # Nth test the hub has ever run, and its standing is judged against all
    # of them (see tradehub.workshop.registry), not just this idea's reruns.
    tests_before = len(supa.table(RUNS).select("id").execute().data or [])
    result = {**result, "registry": {"test_number": tests_before + 1, "tests_before": tests_before}}
    row = {"idea_id": idea_id, "variation": variation, "spec": spec, "draft_model": draft_model,
           "verdict": result["verdict"], "result": result, "data_end": result.get("data_end")}
    # A fresh run is a preview by definition (save-by-choice): the shape carries it.
    return {**supa.table(RUNS).insert(row).execute().data[0], "saved_at": None}


def get_run(supa, run_id: int) -> dict | None:
    rows = supa.table(RUNS).select("*").eq("id", run_id).execute().data
    return rows[0] if rows else None


def _annotate_saved(supa, runs: list[dict]) -> list[dict]:
    """Attach `saved_at` to each run from idea_run_saves (save-by-choice, 2026-11-02).
    idea_runs is append-only, so the save is its own row in another table; this is the
    one place that joins the two, and every reader downstream sees a plain field."""
    if not runs:
        return runs
    saves = supa.table(SAVES).select("run_id,saved_at").execute().data
    by_id = {s["run_id"]: s["saved_at"] for s in saves}
    return [{**r, "saved_at": by_id.get(r["id"])} for r in runs]


def saved_only(runs: list[dict]) -> list[dict]:
    """The runs that count: saved ones, in order. Previews are visible in the
    Workshop and nowhere else -- not the record, not the gate, not tracking."""
    return [r for r in runs if r.get("saved_at")]


def save_run(supa, run_id: int) -> dict | None:
    """Save a preview run (save-by-choice, 2026-11-02): one insert into
    idea_run_saves. Idempotent -- an already-saved run returns as it is."""
    run = get_run(supa, run_id)
    if run is None:
        return None
    existing = supa.table(SAVES).select("run_id,saved_at").eq("run_id", run_id).execute().data
    if not existing:
        stamp = datetime.now(UTC).isoformat()
        try:
            supa.table(SAVES).insert({"run_id": run_id, "saved_at": stamp}).execute()
        except Exception:
            # A racing save won; the row exists, which is all saving means.
            existing = supa.table(SAVES).select("run_id,saved_at").eq("run_id", run_id).execute().data
            if not existing:
                raise
        else:
            existing = [{"run_id": run_id, "saved_at": stamp}]
    return {**run, "saved_at": existing[0]["saved_at"]}


def set_auto(supa, idea_id: int, on: bool, by: str) -> dict:
    """Switch an idea's automatic paper orders on or off; every change is appended to order_switches."""
    row = supa.table(IDEAS).update({"auto_orders": on}).eq("id", idea_id).execute().data[0]
    supa.table(SWITCHES).insert({"idea_id": idea_id, "on": on, "by": by}).execute()
    return row


def auto_ideas(supa) -> list[dict]:
    return [i for i in live_ideas(supa) if i.get("auto_orders")]


def closing_ideas(supa) -> list[dict]:
    """Ideas whose orders were on at some point and are now off (switched off or killed): their shares get closed."""
    ever_on = {r["idea_id"] for r in supa.table(SWITCHES).select("idea_id,on").execute().data if r["on"]}
    return [i for i in _all_ideas(supa) if i["id"] in ever_on and not (i.get("auto_orders") and not i.get("killed_at"))]


def log_orders(supa, idea_id: int, day: str, rows: list[dict], book: str = "main") -> list[dict]:
    if not rows:
        return []
    keep = ("symbol", "side", "qty", "client_order_id", "status", "reason", "alpaca_order_id")
    return supa.table(ORDERS).insert([{"idea_id": idea_id, "day": day, "book": book,
                                       **{k: r.get(k) for k in keep}}
                                      for r in rows]).execute().data


def activation(supa, book: str, idea_id: int) -> dict | None:
    rows = supa.table(ACTIVATIONS).select("*").eq("book", book).eq("idea_id", idea_id).execute().data
    return rows[0] if rows else None


def activations(supa, book: str) -> list[dict]:
    return supa.table(ACTIVATIONS).select("*").eq("book", book).execute().data


def go_live_book(supa, book: str, idea_id: int, run_id: int, size_pct: float, gate: dict) -> dict:
    """Go live on one book. Set-once like the idea-row path: an existing live activation is
    returned unchanged (the caller reports it as already live), never overwritten."""
    existing = activation(supa, book, idea_id)
    if existing and existing.get("live_at"):
        return existing
    row = {"book": book, "idea_id": idea_id, "live_at": datetime.now(UTC).isoformat(),
           "live_run_id": run_id, "size_pct": size_pct, "gate": gate}
    if existing:
        return supa.table(ACTIVATIONS).update(row).eq("book", book).eq("idea_id", idea_id).execute().data[0]
    return supa.table(ACTIVATIONS).insert(row).execute().data[0]


def set_auto_book(supa, book: str, idea_id: int, on: bool, by: str) -> dict:
    row = supa.table(ACTIVATIONS).update({"auto_orders": on}).eq("book", book).eq("idea_id", idea_id).execute().data[0]
    supa.table(SWITCHES).insert({"idea_id": idea_id, "on": on, "by": by, "book": book}).execute()
    return row


def kill_book(supa, book: str, idea_id: int) -> dict:
    return supa.table(ACTIVATIONS).update(
        {"killed_at": datetime.now(UTC).isoformat(), "auto_orders": False}
    ).eq("book", book).eq("idea_id", idea_id).execute().data[0]


def _activation_idea(row: dict) -> dict:
    """An activation shaped like the idea rows the order runner consumes."""
    return {"id": row["idea_id"], "live_run_id": row["live_run_id"], "size_pct": row["size_pct"]}


def auto_activations(supa, book: str) -> list[dict]:
    return [_activation_idea(r) for r in activations(supa, book)
            if r.get("live_at") and r.get("auto_orders") and not r.get("killed_at")]


def closing_activations(supa, book: str) -> list[dict]:
    """Activations whose orders were on at some point on this book and are now off: their
    shares on the book get closed, mirroring closing_ideas for the main book."""
    ever_on = {r["idea_id"] for r in supa.table(SWITCHES).select("idea_id,on").eq("book", book).execute().data
               if r["on"]}
    return [_activation_idea(r) for r in activations(supa, book)
            if r["idea_id"] in ever_on and r.get("live_at")
            and not (r.get("auto_orders") and not r.get("killed_at"))]


def order_log(supa, idea_id: int, limit: int = 100) -> list[dict]:
    return supa.table(ORDERS).select("*").eq("idea_id", idea_id).order("id", desc=True).execute().data[:limit][::-1]


# ── Manual actions (migration 20261102000006) ─────────────────────────────────────
# The auto-trader's hand-off list: things it must not do alone (an unquotable option,
# an expiring short, a spread whose single contract risks more than the budget).
# Deduped on (book, idea, symbol) while open, so a daily runner doesn't stack copies.

def add_critique(supa, idea_id: int, book: str, payload: dict) -> dict:
    """One weekly critique row (loop piece 1). Append-only like the rest of the
    record: the history is what lets the next critique call a pattern repeated."""
    row = {"idea_id": idea_id, "book": book,
           "at": payload.get("at") or datetime.now(UTC).isoformat(), "payload": payload}
    return supa.table(CRITIQUES).insert(row).execute().data[0]


def latest_critiques(supa) -> dict[tuple[int, str], dict]:
    """{(idea_id, book): newest critique row}. Weekly rows are few; the scan is fine."""
    rows = supa.table(CRITIQUES).select("*").order("at", desc=True).execute().data
    out: dict[tuple[int, str], dict] = {}
    for row in rows:
        out.setdefault((row["idea_id"], row["book"]), row)
    return out


def add_manual_action(supa, book: str, idea_id: int | None, kind: str, symbol: str | None,
                      detail: str) -> None:
    """One open action per (book, idea, kind, symbol): the dedupe used to ignore
    the idea (handover item 6), so a second idea's problem on the same symbol
    was swallowed by the first idea's open action and never surfaced."""
    q = (supa.table("manual_actions").select("id")
         .eq("book", book).eq("state", "open").eq("kind", kind))
    q = q.is_("symbol", "null") if symbol is None else q.eq("symbol", symbol)
    q = q.is_("idea_id", "null") if idea_id is None else q.eq("idea_id", idea_id)
    open_rows = q.execute().data or []
    if open_rows:
        return
    supa.table("manual_actions").insert(
        {"book": book, "idea_id": idea_id, "kind": kind, "symbol": symbol,
         "detail": detail}).execute()


def manual_actions(supa, book: str = "main", state: str = "open") -> list[dict]:
    rows = (supa.table("manual_actions").select("*").eq("book", book).eq("state", state)
            .order("created_at").execute().data or [])
    return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)


def resolve_manual_action(supa, action_id: int, state: str) -> None:
    from datetime import datetime, timezone

    supa.table("manual_actions").update(
        {"state": state, "resolved_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", action_id).execute()


MAX_TAGS, MAX_TAG_LEN = 8, 24


def clean_tags(tags: list[str]) -> list[str]:
    """Trimmed, deduplicated ignoring case (the first spelling wins), empty and over-long tags dropped."""
    out: list[str] = []
    for t in tags:
        t = " ".join(str(t).split())
        if t and len(t) <= MAX_TAG_LEN and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:MAX_TAGS]


def set_tags(supa, idea_id: int, tags: list[str]) -> dict:
    """Kevin's own groupings for the Ideas page (2026-11-05). Replaces the idea's tags."""
    clean = clean_tags(tags)
    supa.table(IDEAS).update({"tags": clean}).eq("id", idea_id).execute()
    return {"id": idea_id, "tags": clean}
