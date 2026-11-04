"""The gap tracker's desk: evidence status first, then the model against the market, then the ledger."""

from __future__ import annotations

from datetime import datetime

from tradehub.gaps import logic
from tradehub.gaps.run import POSITIONS, RUNS, SNAPSHOTS

TOP_GAPS = 8
NEAR_MISSES = 25


def desk(supa, now: datetime) -> dict:
    pairs = [{"category": p["category"], "model": float(p["model"]), "market": float(p["market"]),
              "outcome": int(p["outcome"])} for p in supa.rpc("gap_first_pairs").execute().data or []]
    funnel: dict[str, dict[str, int]] = {}
    for row in supa.rpc("gap_funnel").execute().data or []:
        funnel.setdefault(row["category"], {})[row["reason"]] = int(row["n"])
    runs = supa.table(RUNS).select("taken_at,series,error").order("id").execute().data or []
    started = runs[0]["taken_at"] if runs else None
    latest = runs[-1]["taken_at"] if runs else None
    days = (now - datetime.fromisoformat(started)).total_seconds() / 86400 if started else 0.0
    positions = supa.table(POSITIONS).select("*").order("id").execute().data or []
    current = (supa.table(SNAPSHOTS).select("*").eq("taken_at", latest).execute().data or []) if latest else []
    known = [r for r in current if r.get("gap_pts") is not None]
    return {"as_of": latest, "started_at": started,
            "evidence": logic.evidence_status(days=days, pairs=len(pairs)), "grade": logic.grade(pairs),
            "ledger": logic.summarize_ledger(positions),
            "gross_only": any(p.get("pnl_basis", "") and "gross" in p["pnl_basis"] for p in positions)
            or any(p["status"] == "open" and p.get("entry_fee") is None for p in positions),
            "open_positions": [p for p in positions if p["status"] == "open"],
            "closed_positions": [p for p in positions if p["status"] == "closed"][-50:],
            "top_gaps": sorted((r for r in known if r.get("flagged")), key=lambda r: -r["gap_pts"])[:TOP_GAPS],
            "near_misses": sorted((r for r in known if not r.get("flagged")), key=lambda r: -r["gap_pts"])[:NEAR_MISSES],
            "funnel": funnel,
            "series_errors": [r for r in runs if r["taken_at"] == latest and r.get("error")]}
