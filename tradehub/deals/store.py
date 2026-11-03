"""Deal-run records: the run + its inputs + outputs are the record (Part B's
shared rule, mirroring how a screen's spec is its record)."""

from __future__ import annotations

RUNS = "deal_runs"


def save_run(supa, kind: str, name: str, inputs: dict, outputs: dict) -> dict:
    row = {"kind": kind, "name": name, "inputs": inputs, "outputs": outputs}
    return supa.table(RUNS).insert(row).execute().data[0]


def _headline(kind: str, outputs: dict | None) -> dict:
    o = outputs or {}
    if kind == "ipo":
        return {"pw_ps": o.get("pw_ps"), "bear_ps": o.get("bear_ps")}
    offer = o.get("offer") or {}
    fair = o.get("fair_value") or {}
    return {"offer_ps": offer.get("value_ps"), "premium_pct": offer.get("premium_pct"),
            "fair_ps": fair.get("ps")}


def list_runs(supa) -> list[dict]:
    rows = supa.table(RUNS).select("id,kind,name,created_at,summary,outputs").order("id", desc=True).execute().data or []
    out = []
    for r in rows:
        outputs = r.pop("outputs", None)
        out.append({**r, "has_summary": bool(r.pop("summary", None)),
                    "headline": _headline(r["kind"], outputs)})
    return out


def get_run(supa, run_id: int) -> dict | None:
    rows = supa.table(RUNS).select("*").eq("id", run_id).execute().data
    if not rows:
        return None
    return _with_doc(rows[0])


def _with_doc(row: dict) -> dict:
    from tradehub.deals.summary import doc_from_stored

    return {**row, "summary_doc": doc_from_stored(row.get("summary"))}


def set_summary(supa, run_id: int, doc: dict, model: str) -> dict:
    import json

    rows = (supa.table(RUNS).update({"summary": json.dumps(doc), "summary_model": model})
            .eq("id", run_id).execute().data)
    return _with_doc(rows[0]) if rows else None
