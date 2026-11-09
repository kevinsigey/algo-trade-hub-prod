"""Supabase access for Phase 1: valuation_verdicts (append-only),
valuation_verdict_grades (one row per verdict x horizon, upserted),
valuation_watch_state (the band watch's memory) and valuation_triggers
(the pending debate queue, drained by section 5 priority)."""
from __future__ import annotations

VERDICTS = "valuation_verdicts"
GRADES = "valuation_verdict_grades"
WATCH = "valuation_watch_state"
TRIGGERS = "valuation_triggers"


# -- verdicts ---------------------------------------------------------------

def insert_verdict(client, row: dict) -> dict:
    resp = client.table(VERDICTS).insert(row).execute()
    data = resp.data or []
    return data[0] if data else row


def all_verdicts(client) -> list[dict]:
    return (client.table(VERDICTS).select("*")
            .order("rendered_at", desc=True).execute().data) or []


def verdicts_for(client, ticker: str) -> list[dict]:
    return (client.table(VERDICTS).select("*").eq("ticker", ticker)
            .order("rendered_at", desc=True).execute().data) or []


def latest_verdicts(client) -> list[dict]:
    seen: dict[str, dict] = {}
    for row in all_verdicts(client):
        seen.setdefault(row["ticker"], row)
    return [seen[t] for t in sorted(seen)]


def verdicts_since(client, since_iso: str) -> list[dict]:
    return (client.table(VERDICTS).select("*")
            .gte("rendered_at", since_iso).execute().data) or []


# -- grades -----------------------------------------------------------------

def grades_for(client, verdict_id: int) -> list[dict]:
    return (client.table(GRADES).select("*").eq("verdict_id", verdict_id)
            .execute().data) or []


def all_grades(client) -> list[dict]:
    return (client.table(GRADES).select("*").execute().data) or []


def upsert_grade(client, row: dict) -> None:
    client.table(GRADES).upsert(row, on_conflict="verdict_id,horizon").execute()


# -- watch state --------------------------------------------------------------

def watch_state(client, key: str) -> dict | None:
    rows = (client.table(WATCH).select("*").eq("key", key).limit(1)
            .execute().data) or []
    return rows[0] if rows else None


def set_watch_state(client, row: dict) -> None:
    client.table(WATCH).upsert(row, on_conflict="key").execute()


def all_watch_state(client) -> list[dict]:
    return (client.table(WATCH).select("*").execute().data) or []


# -- triggers -----------------------------------------------------------------

def insert_trigger(client, row: dict) -> None:
    client.table(TRIGGERS).insert(row).execute()


def pending_triggers(client) -> list[dict]:
    return (client.table(TRIGGERS).select("*").eq("state", "pending")
            .order("priority").order("created_at").execute().data) or []


def mark_trigger(client, trigger_id: int, state: str,
                 verdict_id: int | None = None) -> None:
    update = {"state": state}
    if verdict_id is not None:
        update["verdict_id"] = verdict_id
    client.table(TRIGGERS).update(update).eq("id", trigger_id).execute()
