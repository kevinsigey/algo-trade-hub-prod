"""Deal-run records: the run + its inputs + outputs are the record (Part B's
shared rule, mirroring how a screen's spec is its record)."""

from __future__ import annotations

RUNS = "deal_runs"


def save_run(supa, kind: str, name: str, inputs: dict, outputs: dict) -> dict:
    row = {"kind": kind, "name": name, "inputs": inputs, "outputs": outputs}
    return supa.table(RUNS).insert(row).execute().data[0]


def list_runs(supa) -> list[dict]:
    rows = supa.table(RUNS).select("id,kind,name,created_at,summary").order("id", desc=True).execute().data or []
    return [{**r, "has_summary": bool(r.pop("summary", None))} for r in rows]


def get_run(supa, run_id: int) -> dict | None:
    rows = supa.table(RUNS).select("*").eq("id", run_id).execute().data
    return rows[0] if rows else None


def set_summary(supa, run_id: int, summary: str, model: str) -> dict:
    rows = supa.table(RUNS).update({"summary": summary, "summary_model": model}).eq("id", run_id).execute().data
    return rows[0] if rows else None
