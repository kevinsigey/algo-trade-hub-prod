"""The gap tracker's desk: evidence status first, then the model against the market, then the ledger."""

from __future__ import annotations

from datetime import datetime

from tradehub.gaps import logic
from tradehub.gaps.run import RUNS, SNAPSHOTS, all_positions, entries_enabled

TOP_GAPS = 8
NEAR_MISSES = 25
PAIR_PAGE = 1000


def _all_pairs(supa) -> list[dict]:
    pairs: list[dict] = []
    after = ""
    while True:
        page = supa.rpc("gap_first_pairs", {"after_ticker": after, "max_rows": PAIR_PAGE}).execute().data or []
        pairs += [{"category": p["category"], "model": float(p["model"]), "market": float(p["market"]),
                   "outcome": int(p["outcome"])} for p in page]
        if len(page) < PAIR_PAGE:
            return pairs
        after = page[-1]["ticker"]


def ledger_by_category(positions: list[dict]) -> dict[str, dict]:
    """Each desk's own closed record over ALL its closed positions — never the capped page of
    trades the payload also carries, so the per-desk lines stay exact as the ledger grows past
    it. The desks reconcile to the shared ledger: their closed counts sum to its resolved count
    and their realized sums to its P&L. A desk with no closed trades reads zeroes and nulls."""
    out: dict[str, dict] = {}
    for category in sorted({p.get("category") for p in positions if p.get("category")}):
        pnls = sorted(float(p["pnl"]) for p in positions
                      if p.get("category") == category and p["status"] == "closed"
                      and p.get("pnl") is not None)
        if not pnls:
            out[category] = {"closed": 0, "realized": 0.0, "win_rate": None, "median_pnl": None}
            continue
        n = len(pnls)
        median = pnls[n // 2] if n % 2 else (pnls[n // 2 - 1] + pnls[n // 2]) / 2
        out[category] = {"closed": n, "realized": round(sum(pnls), 2),
                         "win_rate": sum(v > 0 for v in pnls) / n, "median_pnl": median}
    return out


def _fee_basis(positions: list[dict]) -> str:
    """Whether the paper return is after fees: net, gross, or a mix of the two. Nothing closed reads net."""
    gross = ["gross" in (p.get("pnl_basis") or "") for p in positions if p.get("pnl_basis")]
    return "mixed" if any(gross) and not all(gross) else "gross" if gross and all(gross) else "net"


def _top(rows: list[dict], flagged: bool, cap: int) -> list[dict]:
    """The biggest gaps per category, so one desk's rows can't crowd out the other's."""
    out: list[dict] = []
    for category in sorted({r["category"] for r in rows}):
        mine = (r for r in rows if r["category"] == category and bool(r.get("flagged")) == flagged)
        out += sorted(mine, key=lambda r: -r["gap_pts"])[:cap]
    return out


def desk(supa, now: datetime) -> dict:
    pairs = _all_pairs(supa)
    funnel: dict[str, dict[str, int]] = {}
    for row in supa.rpc("gap_funnel").execute().data or []:
        funnel.setdefault(row["category"], {})[row["reason"]] = int(row["n"])
    first = supa.table(RUNS).select("taken_at").order("id").limit(1).execute().data or []
    recent = supa.table(RUNS).select("taken_at,series,error").order("id", desc=True).limit(20).execute().data or []
    started = first[0]["taken_at"] if first else None
    latest = recent[0]["taken_at"] if recent else None
    days = (now - datetime.fromisoformat(started)).total_seconds() / 86400 if started else 0.0
    positions = all_positions(supa)
    current = (supa.table(SNAPSHOTS).select("*").eq("taken_at", latest).execute().data or []) if latest else []
    known = [r for r in current if r.get("gap_pts") is not None]
    return {"as_of": latest, "started_at": started, "entries_paused": not entries_enabled(supa),
            "evidence": logic.evidence_status(days=days, pairs=len(pairs)), "grade": logic.grade(pairs),
            "ledger": logic.summarize_ledger(positions),
            "ledger_by_category": ledger_by_category(positions),
            "fee_basis": _fee_basis(positions),
            "open_positions": [p for p in positions if p["status"] == "open"],
            "closed_positions": [p for p in positions if p["status"] == "closed"][-50:],
            "top_gaps": _top(known, True, TOP_GAPS),
            "near_misses": _top(known, False, NEAR_MISSES),
            "funnel": funnel,
            "series_errors": [r for r in recent if r["taken_at"] == latest and r.get("error")]}
