"""Counterfactual: would a 0.05 net-edge bar beat the live 0.10 bar on the oil series?

Research only -- reads a snapshot of production tables (data/*.json, pulled
2026-11-09 ~18:17 UTC) and replays the production rule's own functions
(tradehub.oil_fifteen_rule: net_edges, pnl, _stats, in_halt, futures_open)
at two bars over the identical forward window set. Nothing here writes
anywhere or changes the live gate.
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # repo root, for tradehub imports

from tradehub import oil_fifteen_rule as rule  # noqa: E402

DATA = HERE / "data"
SERIES = {"oil_wti_15m": ("WTI", "KXWTI15M"), "oil_brent_15m": ("Brent", "KXBRENT15M"),
          "natgas_15m": ("Natural gas", "KXNATGAS15M")}
BARS = (0.10, 0.05)


def load(name: str):
    return json.loads((DATA / name).read_text())


def _dt(value: str):
    """Parse a snapshot timestamp. The SQL pull renders '2026-11-07 00:05:09+00'
    (space separator) where production's PostgREST read renders ISO 'T' format --
    production compares PREREG_AT as a string on ITS format; on this snapshot the
    comparison must be done on parsed datetimes or every Nov 7 row is misread."""
    from datetime import datetime

    return datetime.fromisoformat(value)


PREREG_DT = None  # set in build_windows from rule.PREREG_AT


def pick_at_bar(p: float, *, yes_ask, yes_bid, bar: float):
    """pick_net with the bar as a parameter -- same side/cost construction."""
    edges = rule.net_edges(p, yes_ask=yes_ask, yes_bid=yes_bid)
    if edges is None:
        return None
    yes_edge, no_edge = edges
    if max(yes_edge, no_edge) < bar - 1e-9:
        return None
    return ("yes", round(yes_ask, 4), yes_edge) if yes_edge >= no_edge else ("no", round(1 - yes_bid, 4), no_edge)


def stats(trades: list[dict]) -> dict:
    return rule._stats(trades)


def build_windows() -> list[dict]:
    global PREREG_DT
    PREREG_DT = _dt(rule.PREREG_AT)
    forecasts = load("forecasts.json")
    settlements = {r["target"]: int(r["outcome"]) for r in load("settlements.json")}
    first: dict[tuple[str, str], dict] = {}
    for r in sorted(forecasts, key=lambda r: _dt(r["frozen_at"])):
        first.setdefault((r["forecaster"], r["target"]), r)
    windows = []
    for (forecaster, target), r in first.items():
        label, code = SERIES[forecaster]
        p = float(r["probability"])
        edges = rule.net_edges(p, yes_ask=r["yes_ask"], yes_bid=r["yes_bid"])
        windows.append({
            "series": label, "code": code, "target": target, "frozen_at": r["frozen_at"],
            "prob": p, "yes_ask": r["yes_ask"], "yes_bid": r["yes_bid"],
            "halt": rule.in_halt(r["frozen_at"]),
            "best_edge": max(edges) if edges is not None else None,
            "forward": _dt(r["frozen_at"]) >= PREREG_DT,
            "session": "open" if rule.futures_open(r["frozen_at"]) else "closed",
            "outcome": settlements.get(target),
        })
    return windows


def record_at_bar(windows: list[dict], bar: float) -> list[dict]:
    """Settled forward trades the gate would have taken at `bar` (production path, bar swapped)."""
    trades = []
    for w in windows:
        if w["halt"] or not w["forward"] or w["outcome"] is None or w["best_edge"] is None:
            continue
        choice = pick_at_bar(w["prob"], yes_ask=w["yes_ask"], yes_bid=w["yes_bid"], bar=bar)
        if choice:
            side, cost, _ = choice
            trades.append({"series": w["series"], "target": w["target"], "frozen_at": w["frozen_at"],
                           "session": w["session"], "side": side, "cost": cost,
                           "best_edge": w["best_edge"], "outcome": w["outcome"],
                           "pnl": rule.pnl(side, cost, w["outcome"])})
    return trades


def band_of(w: dict) -> str:
    e = w["best_edge"]
    if e is None:
        return "no_quote"
    if e < 0:
        return "<0"
    if e < 0.05:
        return "0-5"
    if e < 0.10:
        return "5-10"
    return "10+"


def distribution(windows: list[dict]) -> dict:
    out = {}
    for label in ("WTI", "Brent", "Natural gas"):
        ws = [w for w in windows if w["series"] == label and w["forward"] and not w["halt"]
              and w["best_edge"] is not None]
        es = sorted(w["best_edge"] for w in ws)
        bands: dict[str, int] = {}
        for w in ws:
            bands[band_of(w)] = bands.get(band_of(w), 0) + 1
        out[label] = {
            "windows": len(ws),
            "mean_best_edge": round(statistics.mean(es), 4) if es else None,
            "median_best_edge": round(statistics.median(es), 4) if es else None,
            "p75_best_edge": round(es[int(0.75 * (len(es) - 1))], 4) if es else None,
            "bands": bands,
            "band_shares": {k: round(v / len(ws), 3) for k, v in bands.items()} if ws else {},
        }
    return out


def crosscheck_decisions(windows: list[dict]) -> dict:
    decisions = load("decisions.json")
    mine = {(w["code"], w["target"]): w for w in windows}
    matched = mismatched = only_theirs = 0
    worst = 0.0
    for d in decisions:
        w = mine.get((d["series"], d["target"]))
        if w is None:
            only_theirs += 1
            continue
        if d["best_edge_net"] is None or w["best_edge"] is None:
            continue
        diff = abs(float(d["best_edge_net"]) - w["best_edge"])
        worst = max(worst, diff)
        if diff <= 1e-6:
            matched += 1
        else:
            mismatched += 1
    return {"decisions_rows": len(decisions), "edge_matched": matched,
            "edge_mismatched": mismatched, "worst_diff": worst,
            "decisions_targets_not_in_forecasts": only_theirs}


def offsets_sensitivity() -> dict:
    """At other entry minutes, what would the [0.05,0.10) band have done? Recomputed from the
    offsets rows' own prob/quotes/outcome (their stored pnl only exists at the 0.10 bar)."""
    offsets = load("offsets.json")
    by_off: dict[int, list[dict]] = {}
    for r in offsets:
        by_off.setdefault(int(r["offset_min"]), []).append(r)
    out = {}
    for off in (1, 3, 5, 7, 10, 13):
        rows = by_off.get(off, [])
        groups = {"oil": [], "gas": []}
        for r in rows:
            if r["edge_net"] is None or r["outcome"] is None:
                continue
            e = float(r["edge_net"])
            if not 0.05 <= e < 0.10:
                continue
            choice = pick_at_bar(float(r["prob_up"]), yes_ask=r["yes_ask"], yes_bid=r["yes_bid"], bar=0.05)
            if not choice:
                continue
            side, cost, _ = choice
            rec = {"pnl": rule.pnl(side, cost, int(r["outcome"])), "frozen_at": r["close_time"]}
            groups["gas" if r["series"] == "KXNATGAS15M" else "oil"].append(rec)
        out[off] = {g: stats(ts) for g, ts in groups.items()}
    return out


def main() -> None:
    windows = build_windows()
    result: dict = {"prereg_at": rule.PREREG_AT,
                    "windows_total": len(windows),
                    "crosscheck": crosscheck_decisions(windows),
                    "distribution_forward_freeze": distribution(windows)}
    recs = {bar: record_at_bar(windows, bar) for bar in BARS}
    result["reconcile_010"] = {label: stats([t for t in recs[0.10] if t["series"] == label])
                               for label in ("WTI", "Brent", "Natural gas")}
    result["record_010_all"] = stats(recs[0.10])
    groups = {"WTI": ["WTI"], "Brent": ["Brent"], "Oil (WTI+Brent)": ["WTI", "Brent"],
              "Natural gas": ["Natural gas"], "All": ["WTI", "Brent", "Natural gas"]}
    detail = {}
    for gname, labels in groups.items():
        t10 = [t for t in recs[0.10] if t["series"] in labels]
        t05 = [t for t in recs[0.05] if t["series"] in labels]
        band = [t for t in t05 if t["best_edge"] < 0.10 - 1e-9]
        entry = {"at_010": stats(t10), "at_005": stats(t05), "marginal_band_5_10": stats(band)}
        for sess in ("open", "closed"):
            entry[f"at_010_{sess}"] = stats([t for t in t10 if t["session"] == sess])
            entry[f"at_005_{sess}"] = stats([t for t in t05 if t["session"] == sess])
            entry[f"band_{sess}"] = stats([t for t in band if t["session"] == sess])
        detail[gname] = entry
    result["counterfactual"] = detail
    result["offsets_sensitivity_band_trades"] = offsets_sensitivity()
    (HERE / "results.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
