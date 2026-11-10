"""Saved screens: the spec is the saved object (Screening spec, Kevin
2026-11-02). A screen row carries its last run (footer + survivors + columns)
so what the user saw is the record, and promotion is set-once: a screen
becomes at most one Workshop idea."""

from __future__ import annotations

from datetime import UTC, datetime

from . import membership as membership_mod

SCREENS = "screens"


def _baseline(spec: dict, last_run: dict | None) -> dict | None:
    """The silent baseline state for a diffed screen created with a run:
    the first recorded run establishes membership, it never storms events."""
    if not last_run or not (spec or {}).get("membership_diff"):
        return None
    state, _ = membership_mod.diff_membership(
        None, last_run.get("survivors") or [], membership_mod.run_date_of(last_run))
    return state


def create_screen(supa, name: str, spec: dict, last_run: dict | None = None) -> dict:
    row = {"name": name, "spec": spec, "last_run": last_run}
    state = _baseline(spec, last_run)
    if state is not None:
        row["membership"] = state
    return supa.table(SCREENS).insert(row).execute().data[0]


def _last_run_view(last_run: dict | None) -> dict | None:
    """The saved-screen stamp: when it last ran, how many survived, and
    where the data came from (the run footer's per-column provenance,
    distilled to the distinct sources + the oldest as-of)."""
    if not last_run:
        return None
    footer = last_run.get("footer") or {}
    cols = footer.get("columns") or {}
    sources = sorted({str(v.get("source")) for v in cols.values()
                      if isinstance(v, dict) and v.get("source")})
    view = {"run_at": footer.get("run_at"),
            "survivors": footer.get("survivors"),
            "data_as_of": footer.get("data_as_of"),
            "sources": sources}
    if footer.get("near_misses"):
        view["near_misses"] = footer["near_misses"]
        view["near_miss_count"] = footer.get("near_miss_count",
                                             len(footer["near_misses"]))
    return view


def list_screens(supa) -> list[dict]:
    rows = supa.table(SCREENS).select("*").order("id", desc=True).execute().data or []
    out = []
    for r in rows:
        item = {**r, "last_run": _last_run_view(r.get("last_run"))}
        for key in ("membership", "membership_events"):
            if r.get(key) is not None:
                item[key] = r[key]
        out.append(item)
    return out


def get_screen(supa, screen_id: int) -> dict | None:
    rows = supa.table(SCREENS).select("*").eq("id", screen_id).execute().data
    return rows[0] if rows else None


def record_run(supa, screen_id: int, last_run: dict) -> dict:
    values = {"last_run": last_run, "updated_at": datetime.now(UTC).isoformat()}
    existing = get_screen(supa, screen_id)
    if existing and (existing.get("spec") or {}).get("membership_diff"):
        # Watchlist diffing (classic three): the refresh is diffed against
        # the stored membership; entrances/exits append dated events, the
        # first diffed run baselines silently (see screening/membership.py).
        state, events = membership_mod.diff_membership(
            existing.get("membership"), last_run.get("survivors") or [],
            membership_mod.run_date_of(last_run))
        values["membership"] = state
        if events:
            values["membership_events"] = membership_mod.append_events(
                existing.get("membership_events"), events)
    rows = supa.table(SCREENS).update(values).eq("id", screen_id).execute().data
    return rows[0] if rows else None


def set_promoted(supa, screen_id: int, idea_id: int) -> dict:
    rows = supa.table(SCREENS).update(
        {"promoted_idea_id": idea_id, "promoted_at": datetime.now(UTC).isoformat(),
         "updated_at": datetime.now(UTC).isoformat()}
    ).eq("id", screen_id).execute().data
    return rows[0] if rows else None


def delete_screen(supa, screen_id: int) -> None:
    supa.table(SCREENS).delete().eq("id", screen_id).execute()
