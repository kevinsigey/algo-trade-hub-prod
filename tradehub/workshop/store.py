"""Ideas, their runs, shadow days and order labels in Supabase.

Runs, shadow days and labels are insert-only (DB triggers). An idea's published/live/killed timestamps are set once:
the update only matches while the column is still null, and the DB trigger refuses any later change.
"""

from __future__ import annotations

from datetime import UTC, datetime

IDEAS, RUNS, SHADOW, LABELS = "ideas", "idea_runs", "idea_shadow_days", "order_labels"
SWITCHES, ORDERS = "order_switches", "paper_orders"


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


def kill(supa, idea_id: int) -> dict:
    return _set_once(supa, idea_id, "killed_at", {"auto_orders": False})  # a killed idea never trades again


def _all_ideas(supa) -> list[dict]:
    # ponytail: whole-table read; filter in SQL if ideas ever number in the thousands
    return supa.table(IDEAS).select("*").order("created_at", desc=True).execute().data


def live_ideas(supa) -> list[dict]:
    return [i for i in _all_ideas(supa) if i.get("live_at") and not i.get("killed_at")]


def published_ideas(supa) -> list[dict]:
    return [i for i in _all_ideas(supa) if i.get("published_at")]


def shadow_days(supa, idea_id: int) -> list[dict]:
    return supa.table(SHADOW).select("*").eq("idea_id", idea_id).order("day").execute().data


def append_shadow(supa, idea_id: int, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    return supa.table(SHADOW).insert([{"idea_id": idea_id, **r} for r in rows]).execute().data


def add_label(supa, order_id: str, idea_id: int | None, by: str) -> dict:
    return supa.table(LABELS).insert({"order_id": order_id, "idea_id": idea_id, "by": by}).execute().data[0]


def label_history(supa) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in supa.table(LABELS).select("*").order("id").execute().data:
        out.setdefault(r["order_id"], []).append(r)
    return out


def labels(supa) -> dict[str, int | None]:
    """The current label per order id: the latest relabel wins."""
    return {order: rows[-1]["idea_id"] for order, rows in label_history(supa).items()}


def create_idea(supa, title: str, plain_words: str) -> dict:
    return supa.table(IDEAS).insert({"title": title, "plain_words": plain_words}).execute().data[0]


def get_idea(supa, idea_id: int) -> dict | None:
    rows = supa.table(IDEAS).select("*").eq("id", idea_id).execute().data
    if not rows:
        return None
    runs = supa.table(RUNS).select("*").eq("idea_id", idea_id).order("variation").execute().data
    return {"idea": rows[0], "runs": runs}


def list_ideas(supa) -> list[dict]:
    ideas = supa.table(IDEAS).select("*").order("created_at", desc=True).execute().data
    runs = supa.table(RUNS).select("idea_id,variation,verdict").execute().data
    latest: dict[int, tuple[int, str]] = {}
    for r in runs:
        if r["variation"] > latest.get(r["idea_id"], (0, ""))[0]:
            latest[r["idea_id"]] = (r["variation"], r["verdict"])
    return [{"id": i["id"], "title": i["title"], "created_at": i["created_at"],
             "runs": latest.get(i["id"], (0, None))[0], "latest_verdict": latest.get(i["id"], (0, None))[1]}
            for i in ideas]


def insert_run(supa, idea_id: int, variation: int, spec: dict, draft_model: str | None, result: dict) -> dict:
    row = {"idea_id": idea_id, "variation": variation, "spec": spec, "draft_model": draft_model,
           "verdict": result["verdict"], "result": result, "data_end": result.get("data_end")}
    return supa.table(RUNS).insert(row).execute().data[0]


def get_run(supa, run_id: int) -> dict | None:
    rows = supa.table(RUNS).select("*").eq("id", run_id).execute().data
    return rows[0] if rows else None


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


def log_orders(supa, idea_id: int, day: str, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    keep = ("symbol", "side", "qty", "client_order_id", "status", "reason", "alpaca_order_id")
    return supa.table(ORDERS).insert([{"idea_id": idea_id, "day": day, **{k: r.get(k) for k in keep}}
                                      for r in rows]).execute().data


def order_log(supa, idea_id: int, limit: int = 100) -> list[dict]:
    return supa.table(ORDERS).select("*").eq("idea_id", idea_id).order("id", desc=True).execute().data[:limit][::-1]
