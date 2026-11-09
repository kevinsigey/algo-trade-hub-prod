"""Entry-timing study: for the 15-minute rule's OIL series, does entering earlier
than the ~minute-5 freeze beat the freeze entry, at the live 0.10 net-edge bar?

Research only -- reads a snapshot of production tables (data/*.json, pulled
2026-11-09 ~18:47 UTC) and replays the production rule's own functions
(tradehub.oil_fifteen_rule: net_edges, pick_net, pnl, _stats, in_halt,
futures_open). Nothing here writes anywhere or changes the live rule.

ANALYSIS PLAN (stated before results, per the commissioning brief):

Cohort. fifteen_window_offsets joined to fifteen_rule_decisions on
(series, target). A window is in the cohort when its decision row's frozen_at
(parsed as a datetime -- never string-compared; the +5-bar study found the
SQL pull's space-separated timestamps silently drop rows under a string
compare) is >= PREREG_AT (2026-11-07T00:00Z), the window is not in the
futures halt (rule.in_halt on frozen_at), and it is settled (outcome known).

Validation, before any timing read:
  V1. The forecasts replay at the 0.10 bar (first freeze per window, the
      +5 study's machinery) reproduces the live gated record.
  V2. The offsets table at offset 5 (the freeze minute: every decision's
      frozen_at is window_open + 5 min) reproduces the decisions table's
      forward buy record, up to windows whose offset-5 row is not
      tick-priced.
  V3. Offsets outcomes agree with journal settlements; offsets@5 best
      edges agree with the decisions table's best_edge_net.

Reads, per offset k in 0..15, for WTI, Brent, Oil (WTI+Brent) and NatGas
(the reference series):
  R1. Coverage: cohort windows with a row at k, split by prob_source
      (tick = captured live by the every-minute tape recorder, with real
      quotes; tape = recomputed later from candles, never carries quotes,
      so never priced). Priced = edge_net present.
  R2. The hypothetical record at the live bar on priced windows: the
      stored pnl (written only when pick_net cleared 0.10 at that
      minute), summarised by rule._stats.
  R3. PAIRED comparison vs offset 5 on the intersection of windows priced
      at BOTH minutes: per window, policy pnl at k (stored pnl, else 0 --
      the gate not passing at k means no trade, not a missing value) and
      at 5 likewise; the delta series' mean / low95 (same 1.96 formula).
      Plus the both-pass subset (gate passed at both minutes): mean pnl
      each side and side flips -- the pure timing effect on one trade set.
  R4. The [0.05, 0.10) band by offset: pick recomputed at a 0.05 bar from
      the row's own prob/quotes (stored pnl only exists at 0.10), trades
      with best net edge in [0.05, 0.10) -- does early entry rescue the
      band the +5 study rejected at the freeze?
  R5. Session splits (open/closed) of the R3 paired delta where the
      intersection holds >= 20 windows; smaller slices are reported as
      suppressed, never dressed up.

VERDICT BAR (pre-stated): timing is a real lever only if an earlier offset
beats offset 5 on the paired intersection for BOTH oil series in the same
direction with material magnitude, ideally with the paired delta's low95
excluding 0. Anything less is NOT PROVEN, with the reason named.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))  # repo root, for tradehub imports

from tradehub import oil_fifteen_rule as rule  # noqa: E402

DATA = HERE / "data"
SERIES = {"KXWTI15M": "WTI", "KXBRENT15M": "Brent", "KXNATGAS15M": "Natural gas"}
GROUPS = {"WTI": ["WTI"], "Brent": ["Brent"], "Oil (WTI+Brent)": ["WTI", "Brent"],
          "Natural gas": ["Natural gas"]}
FREEZE_OFFSET = 5
PREREG_DT = datetime.fromisoformat(rule.PREREG_AT)


def load(name: str):
    return json.loads((DATA / name).read_text())


def _dt(value):
    return datetime.fromisoformat(value) if value else None


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


def build_cohort() -> tuple[dict, list[dict]]:
    """{(series_label, target): decision info} for the forward, non-halt, settled cohort."""
    decisions = load("decisions.json")
    cohort = {}
    for d in decisions:
        frozen = _dt(d["frozen_at"])
        if frozen is None or frozen < PREREG_DT:
            continue
        if rule.in_halt(d["frozen_at"]):
            continue
        if d["outcome"] is None:
            continue
        cohort[(SERIES[d["series"]], d["target"])] = {
            "series": SERIES[d["series"]], "target": d["target"],
            "frozen_at": d["frozen_at"], "session": d["session"],
            "outcome": int(d["outcome"]), "action": d["action"],
            "dec_pnl": d["pnl"], "dec_best_edge": d["best_edge_net"],
            "dec_side": d["side"], "dec_cost": d["cost"],
        }
    offsets = load("offsets.json")
    rows = []
    for r in offsets:
        key = (SERIES[r["series"]], r["target"])
        if key not in cohort:
            continue
        rows.append({**r, "series_label": SERIES[r["series"]]})
    return cohort, rows


def validate(cohort: dict, rows: list[dict]) -> dict:
    out = {}
    # V1: forecasts replay at 0.10 (the +5 study's machinery, first freeze per window).
    forecasts = load("forecasts.json")
    settlements = {r["target"]: int(r["outcome"]) for r in load("settlements.json")}
    name_of = {"oil_wti_15m": "WTI", "oil_brent_15m": "Brent", "natgas_15m": "Natural gas"}
    first: dict[tuple[str, str], dict] = {}
    for r in sorted(forecasts, key=lambda r: _dt(r["frozen_at"])):
        first.setdefault((r["forecaster"], r["target"]), r)
    trades = []
    for (fc, target), r in first.items():
        label = name_of[fc]
        if (label, target) not in cohort:
            continue
        ya = float(r["yes_ask"]) if r["yes_ask"] is not None else None
        yb = float(r["yes_bid"]) if r["yes_bid"] is not None else None
        choice = rule.pick_net(float(r["probability"]), yes_ask=ya, yes_bid=yb)
        if choice:
            side, cost, _ = choice
            trades.append({"pnl": rule.pnl(side, cost, settlements[target]),
                           "frozen_at": r["frozen_at"], "series": label})
    out["v1_replay_record"] = stats(trades)
    out["v1_replay_by_series"] = {g: stats([t for t in trades if t["series"] in ls])
                                  for g, ls in GROUPS.items()}
    dec_buys = [{"pnl": c["dec_pnl"], "frozen_at": c["frozen_at"], "series": c["series"]}
                for c in cohort.values() if c["action"] == "buy" and c["dec_pnl"] is not None]
    out["decisions_buy_record"] = stats(dec_buys)
    out["decisions_buy_by_series"] = {g: stats([t for t in dec_buys if t["series"] in ls])
                                      for g, ls in GROUPS.items()}
    # V2 + V3 on the offset-5 rows.
    off5 = {(r["series_label"], r["target"]): r for r in rows if r["offset_min"] == FREEZE_OFFSET}
    rec5 = [{"pnl": r["pnl"], "frozen_at": r["target"], "series": r["series_label"]}
            for r in off5.values() if r["pnl"] is not None]
    out["v2_offsets5_record"] = stats(rec5)
    out["v2_offsets5_by_series"] = {g: stats([t for t in rec5 if t["series"] in ls])
                                    for g, ls in GROUPS.items()}
    # windows where the decision bought but offset-5 has no priced pnl (and vice versa)
    dec_buy_keys = {(c["series"], c["target"]) for c in cohort.values() if c["action"] == "buy"}
    off5_pnl_keys = {k for k, r in off5.items() if r["pnl"] is not None}
    out["v2_decision_buy_not_priced_at_5"] = sorted(dec_buy_keys - off5_pnl_keys)
    out["v2_priced_at_5_not_decision_buy"] = sorted(off5_pnl_keys - dec_buy_keys)
    mism = matched = 0
    worst = 0.0
    for key, r in off5.items():
        c = cohort[key]
        if r["edge_net"] is None or c["dec_best_edge"] is None:
            continue
        diff = abs(float(r["edge_net"]) - float(c["dec_best_edge"]))
        worst = max(worst, diff)
        if diff <= 0.0051:  # offsets store prob rounded to 5dp; edges can differ by rounding
            matched += 1
        else:
            mism += 1
    out["v3_edge5_vs_decisions"] = {"matched_within_rounding": matched, "beyond": mism,
                                    "worst_abs_diff": round(worst, 5)}
    out_mism = sum(1 for r in rows if int(r["outcome"]) != cohort[(r["series_label"], r["target"])]["outcome"])
    st_mism = sum(1 for key, c in cohort.items()
                  if settlements.get(c["target"]) is not None and settlements[c["target"]] != c["outcome"])
    out["v3_outcome_mismatches"] = {"offsets_vs_decisions": out_mism,
                                    "settlements_vs_decisions": st_mism}
    return out


def by_offset(rows: list[dict]) -> dict[int, dict[tuple[str, str], dict]]:
    out: dict[int, dict[tuple[str, str], dict]] = {}
    for r in rows:
        out.setdefault(int(r["offset_min"]), {})[(r["series_label"], r["target"])] = r
    return out


def coverage_and_records(cohort: dict, off: dict) -> dict:
    result = {}
    n_cohort = {g: sum(1 for c in cohort.values() if c["series"] in ls) for g, ls in GROUPS.items()}
    for k in range(16):
        rows_k = off.get(k, {})
        entry = {"cohort_windows": n_cohort}
        for g, labels in GROUPS.items():
            rs = [r for (lab, _t), r in rows_k.items() if lab in labels]
            tick = [r for r in rs if r["prob_source"] == "tick"]
            tape = [r for r in rs if r["prob_source"] == "tape"]
            priced = [r for r in rs if r["edge_net"] is not None]
            trades = [{"pnl": r["pnl"], "frozen_at": r["target"]} for r in rs if r["pnl"] is not None]
            entry[g] = {"windows_with_row": len(rs), "tick_rows": len(tick), "tape_rows": len(tape),
                        "tick_share": round(len(tick) / len(rs), 3) if rs else None,
                        "priced": len(priced), "record": stats(trades),
                        "mean_edge_on_offer": round(sum(float(r["edge_net"]) for r in priced) / len(priced), 4)
                        if priced else None}
        result[k] = entry
    return result


def paired(cohort: dict, off: dict) -> dict:
    """R3: per offset, paired policy-pnl delta vs the freeze offset on the priced intersection."""
    base = off.get(FREEZE_OFFSET, {})
    result = {}
    for k in range(16):
        if k == FREEZE_OFFSET:
            continue
        rows_k = off.get(k, {})
        entry = {}
        for g, labels in GROUPS.items():
            keys = [key for key in cohort
                    if key[0] in labels and key in rows_k and key in base
                    and rows_k[key]["edge_net"] is not None and base[key]["edge_net"] is not None]
            deltas, both_k, both_5, flips = [], [], [], 0
            trades_k = trades_5 = 0
            for key in keys:
                rk, r5 = rows_k[key], base[key]
                pk = rk["pnl"] if rk["pnl"] is not None else 0.0
                p5 = r5["pnl"] if r5["pnl"] is not None else 0.0
                trades_k += rk["pnl"] is not None
                trades_5 += r5["pnl"] is not None
                deltas.append({"pnl": round(pk - p5, 4), "frozen_at": key[1]})
                if rk["pnl"] is not None and r5["pnl"] is not None:
                    both_k.append({"pnl": rk["pnl"], "frozen_at": key[1]})
                    both_5.append({"pnl": r5["pnl"], "frozen_at": key[1]})
                    if rk["side"] != r5["side"]:
                        flips += 1
            d_stats = stats(deltas)
            entry[g] = {"intersection_windows": len(keys), "trades_at_k": trades_k,
                        "trades_at_freeze": trades_5,
                        "paired_delta": {"mean": d_stats["net_per_contract"],
                                         "low95": d_stats["low95"], "total": d_stats["total"]},
                        "both_pass_n": len(both_k),
                        "both_pass_mean_at_k": stats(both_k)["net_per_contract"],
                        "both_pass_mean_at_freeze": stats(both_5)["net_per_contract"],
                        "side_flips_within_both_pass": flips}
        result[k] = entry
    return result


def paired_by_session(cohort: dict, off: dict) -> dict:
    base = off.get(FREEZE_OFFSET, {})
    result = {}
    for k in (1, 2, 3, 4):
        rows_k = off.get(k, {})
        entry = {}
        for g, labels in GROUPS.items():
            per_session = {}
            for sess in ("open", "closed"):
                keys = [key for key, c in cohort.items()
                        if key[0] in labels and c["session"] == sess and key in rows_k and key in base
                        and rows_k[key]["edge_net"] is not None and base[key]["edge_net"] is not None]
                if len(keys) < 20:
                    per_session[sess] = {"suppressed": True, "intersection_windows": len(keys)}
                    continue
                deltas = []
                for key in keys:
                    rk, r5 = rows_k[key], base[key]
                    pk = rk["pnl"] if rk["pnl"] is not None else 0.0
                    p5 = r5["pnl"] if r5["pnl"] is not None else 0.0
                    deltas.append({"pnl": round(pk - p5, 4), "frozen_at": key[1]})
                d = stats(deltas)
                per_session[sess] = {"intersection_windows": len(keys),
                                     "paired_delta_mean": d["net_per_contract"],
                                     "paired_delta_low95": d["low95"]}
            entry[g] = per_session
        result[k] = entry
    return result


def band_by_offset(rows: list[dict]) -> dict:
    result = {}
    by_k: dict[int, list[dict]] = {}
    for r in rows:
        by_k.setdefault(int(r["offset_min"]), []).append(r)
    for k in range(16):
        entry = {}
        for g, labels in GROUPS.items():
            trades = []
            for r in by_k.get(k, []):
                if r["series_label"] not in labels or r["edge_net"] is None:
                    continue
                e = float(r["edge_net"])
                if not 0.05 <= e < 0.10:
                    continue
                choice = pick_at_bar(float(r["prob_up"]), yes_ask=r["yes_ask"],
                                      yes_bid=r["yes_bid"], bar=0.05)
                if not choice:
                    continue
                side, cost, _ = choice
                trades.append({"pnl": rule.pnl(side, cost, int(r["outcome"])),
                               "frozen_at": r["target"]})
            s = stats(trades)
            entry[g] = {**s, "reportable": s["n"] >= 10}
        result[k] = entry
    return result


def variant_minute1_bar005(cohort: dict, off: dict) -> dict:
    """R6: the concrete candidate the two studies jointly suggest -- OIL ONLY,
    enter at minute 1 with a 0.05 net-edge bar -- scored two ways: its own
    record at minute 1 (all priced minute-1 windows, pick recomputed at
    0.05), and its per-window policy pnl paired against the live freeze
    policy (the decisions table's actual buys) on cohort windows priced at
    minute 1. Gas at minute 1 / 0.05 as the reference."""
    rows_1 = off.get(1, {})
    out = {}
    for g, labels in GROUPS.items():
        trades = []
        for (lab, target), r in rows_1.items():
            if lab not in labels or r["edge_net"] is None:
                continue
            choice = pick_at_bar(float(r["prob_up"]), yes_ask=r["yes_ask"],
                                  yes_bid=r["yes_bid"], bar=0.05)
            if not choice:
                continue
            side, cost, _ = choice
            trades.append({"pnl": rule.pnl(side, cost, int(r["outcome"])),
                           "frozen_at": target})
        out[g] = {"record": stats(trades)}
    # policy pairing, oil only: variant pnl (0 when the variant passes) vs the
    # live rule's realised pnl on the same window (decisions pnl, 0 when it skipped)
    keys = [key for key, c in cohort.items()
            if key[0] in ("WTI", "Brent") and key in rows_1 and rows_1[key]["edge_net"] is not None]
    deltas = []
    for key in keys:
        r = rows_1[key]
        choice = pick_at_bar(float(r["prob_up"]), yes_ask=r["yes_ask"],
                              yes_bid=r["yes_bid"], bar=0.05)
        pv = rule.pnl(choice[0], choice[1], int(r["outcome"])) if choice else 0.0
        c = cohort[key]
        pl = c["dec_pnl"] if c["action"] == "buy" and c["dec_pnl"] is not None else 0.0
        deltas.append({"pnl": round(pv - pl, 4), "frozen_at": key[1]})
    d = stats(deltas)
    out["oil_policy_paired_vs_live"] = {"windows": len(keys),
                                        "delta_mean": d["net_per_contract"],
                                        "delta_low95": d["low95"], "delta_total": d["total"]}
    return out


def main() -> None:
    cohort, rows = build_cohort()
    off = by_offset(rows)
    result = {"prereg_at": rule.PREREG_AT, "min_edge_live_bar": rule.MIN_EDGE,
              "cohort_windows": len(cohort),
              "cohort_by_series": {g: sum(1 for c in cohort.values() if c["series"] in ls)
                                   for g, ls in GROUPS.items()},
              "validation": validate(cohort, rows),
              "coverage_and_records_by_offset": coverage_and_records(cohort, off),
              "paired_vs_freeze": paired(cohort, off),
              "paired_by_session": paired_by_session(cohort, off),
              "band_5_10_by_offset": band_by_offset(rows),
              "variant_minute1_bar005": variant_minute1_bar005(cohort, off)}
    (HERE / "results.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
