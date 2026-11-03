"""Saved screens: the spec is the saved object (Screening spec, Kevin
2026-11-02). A screen row carries its last run (footer + survivors + columns)
so what the user saw is the record, and promotion is set-once: a screen
becomes at most one Workshop idea."""

from __future__ import annotations

from datetime import UTC, datetime

SCREENS = "screens"


def create_screen(supa, name: str, spec: dict, last_run: dict | None = None) -> dict:
    row = {"name": name, "spec": spec, "last_run": last_run}
    return supa.table(SCREENS).insert(row).execute().data[0]


def list_screens(supa) -> list[dict]:
    rows = supa.table(SCREENS).select("*").order("id", desc=True).execute().data or []
    return [{**r, "last_run": ({"run_at": (r.get("last_run") or {}).get("footer", {}).get("run_at"),
                                "survivors": (r.get("last_run") or {}).get("footer", {}).get("survivors")}
                               if r.get("last_run") else None)} for r in rows]


def get_screen(supa, screen_id: int) -> dict | None:
    rows = supa.table(SCREENS).select("*").eq("id", screen_id).execute().data
    return rows[0] if rows else None


def record_run(supa, screen_id: int, last_run: dict) -> dict:
    rows = supa.table(SCREENS).update(
        {"last_run": last_run, "updated_at": datetime.now(UTC).isoformat()}
    ).eq("id", screen_id).execute().data
    return rows[0] if rows else None


def set_promoted(supa, screen_id: int, idea_id: int) -> dict:
    rows = supa.table(SCREENS).update(
        {"promoted_idea_id": idea_id, "promoted_at": datetime.now(UTC).isoformat(),
         "updated_at": datetime.now(UTC).isoformat()}
    ).eq("id", screen_id).execute().data
    return rows[0] if rows else None


def delete_screen(supa, screen_id: int) -> None:
    supa.table(SCREENS).delete().eq("id", screen_id).execute()
