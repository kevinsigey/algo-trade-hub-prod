"""Residual-quantile calibration of the 15-minute forecasters — the study frozen in
PREREGISTRATION.md (sha256 1a2ecf81fd81466ccee2e72f3e83b16fe533ac8782a8abe341f323b7e8c1367c).

Reads the audited snapshot in data/{wti,brent,natgas}.json (324 settled v2 windows per
series, 2026-11-04 12:20 UTC -> 2026-11-09 17:05 UTC) and writes results.json.
The gated replay calls tradehub.oil_fifteen_rule's own evaluate/pnl/_stats, so the
gate semantics are production's by construction, not a re-implementation.

Run: PYTHONPATH=<repo root> <venv python> -m research.fifteen_calibration.run
"""

from __future__ import annotations

import bisect
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from tradehub.oil_fifteen_rule import _stats as rule_stats
from tradehub.oil_fifteen_rule import evaluate, pnl

HERE = Path(__file__).parent
CLIP_LO, CLIP_HI = 0.005, 0.995
TRAIN0, BLOCK, MIN_TAIL = 120, 24, 8
BOOT_BLOCK, BOOT_REPS, BOOT_SEED = 16, 4000, 20261109
SERIES = {"wti": "WTI", "brent": "Brent", "natgas": "Natural gas"}


def clip(p: float) -> float:
    return min(CLIP_HI, max(CLIP_LO, p))


# ── calibration maps ─────────────────────────────────────────────────────────

def _pava(values: list[float], weights: list[float]) -> list[float]:
    """Weighted pool-adjacent-violators: the isotonic (nondecreasing) fit."""
    vals, wts, counts = list(values), list(weights), [1] * len(values)
    i = 0
    while i < len(vals) - 1:
        if vals[i] <= vals[i + 1]:
            i += 1
            continue
        w = wts[i] + wts[i + 1]
        vals[i] = (vals[i] * wts[i] + vals[i + 1] * wts[i + 1]) / w
        wts[i] = w
        counts[i] += counts[i + 1]
        del vals[i + 1], wts[i + 1], counts[i + 1]
        if i > 0:
            i -= 1
    out: list[float] = []
    for v, c in zip(vals, counts):
        out += [v] * c
    return out


class IsotonicBins:
    """PRIMARY map: decile bins of the training probabilities, PAVA on (bin mean
    stated prob, bin realized frequency) weighted by bin count."""

    def __init__(self, probs: list[float], outcomes: list[int], n_bins: int = 10):
        order = sorted(range(len(probs)), key=lambda i: probs[i])
        sp = [probs[i] for i in order]
        so = [outcomes[i] for i in order]
        n = len(sp)
        edges = sorted({sp[min(n - 1, (k * n) // n_bins)] for k in range(1, n_bins)})
        bins: list[list[int]] = [[] for _ in range(len(edges) + 1)]
        for idx, p in enumerate(sp):
            bins[bisect.bisect_right(edges, p)].append(idx)
        # merge any bin with < 5 training windows into its neighbour
        changed = True
        while changed and len(bins) > 1:
            changed = False
            for j, b in enumerate(bins):
                if 0 < len(b) < 5:
                    tgt = j - 1 if j > 0 else j + 1
                    bins[tgt] = sorted(bins[tgt] + b)
                    del bins[j]
                    changed = True
                    break
            else:
                for j, b in enumerate(bins):
                    if len(b) == 0:
                        del bins[j]
                        changed = True
                        break
        self.bin_edges: list[float] = []
        stats = []
        for b in bins:
            ps = [sp[i] for i in b]
            os_ = [so[i] for i in b]
            stats.append({"n": len(b), "mean_prob": sum(ps) / len(ps),
                          "freq": sum(os_) / len(os_), "lo": min(ps), "hi": max(ps)})
            self.bin_edges.append(max(ps))
        fitted = _pava([s["freq"] for s in stats], [float(s["n"]) for s in stats])
        for s, f in zip(stats, fitted):
            s["fitted"] = f
        self.bins = stats

    def apply(self, p: float) -> float:
        p = clip(p)
        for j, s in enumerate(self.bins):
            if p <= s["hi"] or j == len(self.bins) - 1:
                return clip(s["fitted"])
        return clip(self.bins[-1]["fitted"])

    def table(self) -> list[dict]:
        return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}
                for s in self.bins]


class Platt:
    """VARIANT map: logistic regression of outcome on logit(stated prob)."""

    def __init__(self, probs: list[float], outcomes: list[int]):
        x = np.array([math.log(clip(p) / (1 - clip(p))) for p in probs])
        y = np.array(outcomes, dtype=float)
        a, b = 0.0, 1.0
        for _ in range(100):
            z = a + b * x
            mu = 1 / (1 + np.exp(-z))
            w = np.clip(mu * (1 - mu), 1e-9, None)
            g = np.array([np.sum(y - mu), np.sum(x * (y - mu))])
            h = np.array([[np.sum(w), np.sum(x * w)], [np.sum(x * w), np.sum(x * x * w)]])
            step = np.linalg.solve(h + 1e-9 * np.eye(2), g)
            a, b = a + float(step[0]), b + float(step[1])
            if max(abs(step)) < 1e-10:
                break
        self.a, self.b = a, b

    def apply(self, p: float) -> float:
        z = self.a + self.b * math.log(clip(p) / (1 - clip(p)))
        return clip(1 / (1 + math.exp(-z)))


# ── scoring ──────────────────────────────────────────────────────────────────

def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logscore(p: float, y: int) -> float:
    p = clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def moving_block_ci(diffs: list[float], *, block: int = BOOT_BLOCK,
                    reps: int = BOOT_REPS, seed: int = BOOT_SEED) -> tuple[float, float]:
    """95% percentile CI for the mean of `diffs` under a moving-block bootstrap."""
    rng = np.random.default_rng(seed)
    x = np.array(diffs)
    n = len(x)
    starts_max = n - block
    means = np.empty(reps)
    for r in range(reps):
        idx: list[int] = []
        while len(idx) < n:
            s = int(rng.integers(0, starts_max + 1))
            idx += list(range(s, s + block))
        means[r] = x[idx[:n]].mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def folds(n: int) -> list[tuple[int, int]]:
    """(train_end, block_end) pairs: initial TRAIN0, then BLOCK-sized blocks,
    a trailing remainder < MIN_TAIL merged into the last block."""
    cuts = []
    end = TRAIN0
    while end < n:
        nxt = min(n, end + BLOCK)
        if n - nxt < MIN_TAIL:
            nxt = n
        cuts.append((end, nxt))
        end = nxt
    return cuts


def decile_curve(probs: list[float], outcomes: list[int]) -> list[dict]:
    """Descriptive calibration curve: stated-prob deciles vs realized frequency."""
    pairs = sorted(zip(probs, outcomes))
    n = len(pairs)
    out = []
    for k in range(10):
        chunk = pairs[(k * n) // 10: ((k + 1) * n) // 10]
        if chunk:
            out.append({"n": len(chunk),
                        "mean_stated": round(sum(p for p, _ in chunk) / len(chunk), 4),
                        "freq": round(sum(y for _, y in chunk) / len(chunk), 4)})
    return out


# ── the study ────────────────────────────────────────────────────────────────

def run_series(key: str, rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda r: (r["frozen_at"], r["target"]))
    oof: list[dict] = []
    fold_rows = []
    repro = None
    for fi, (train_end, block_end) in enumerate(folds(len(rows))):
        train = rows[:train_end]
        block = rows[train_end:block_end]
        iso_model = IsotonicBins([r["p_model"] for r in train], [r["outcome"] for r in train])
        platt_model = Platt([r["p_model"] for r in train], [r["outcome"] for r in train])
        iso_mkt = IsotonicBins([r["p_mkt"] for r in train], [r["outcome"] for r in train])
        fold_rows.append({"fold": fi + 1, "train_n": train_end,
                          "block": [block[0]["frozen_at"], block[-1]["frozen_at"]],
                          "block_n": len(block)})
        for r in block:
            oof.append({**r,
                        "p_iso": iso_model.apply(r["p_model"]),
                        "p_platt": platt_model.apply(r["p_model"]),
                        "m_iso": iso_mkt.apply(r["p_mkt"])})
        if key == "wti" and fi == len(folds(len(rows))) - 1:
            r0 = block[0]
            repro = {"target": r0["target"], "frozen_at": r0["frozen_at"],
                     "fold": fi + 1, "train_n": train_end,
                     "train_span": [train[0]["frozen_at"], train[-1]["frozen_at"]],
                     "p_model": r0["p_model"], "p_mkt": r0["p_mkt"],
                     "yes_bid": r0["yes_bid"], "yes_ask": r0["yes_ask"],
                     "outcome": r0["outcome"], "p_iso": iso_model.apply(r0["p_model"]),
                     "platt_ab": [round(platt_model.a, 4), round(platt_model.b, 4)],
                     "iso_table": iso_model.table()}
    n_oof = len(oof)
    arms = {"raw_model": "p_model", "iso_model": "p_iso", "platt_model": "p_platt",
            "raw_market": "p_mkt", "iso_market": "m_iso"}
    scores = {}
    for name, col in arms.items():
        scores[name] = {
            "brier": round(sum(brier(r[col], r["outcome"]) for r in oof) / n_oof, 5),
            "logscore": round(sum(logscore(r[col], r["outcome"]) for r in oof) / n_oof, 5)}
    diffs = {}
    for name, col in (("iso_model", "p_iso"), ("platt_model", "p_platt"), ("iso_market", "m_iso")):
        base = "p_mkt" if name == "iso_market" else "p_model"
        d = [brier(r[col], r["outcome"]) - brier(r[base], r["outcome"]) for r in oof]
        lo, hi = moving_block_ci(d)
        diffs[name] = {"mean_diff": round(float(np.mean(d)), 5), "ci95": [round(lo, 5), round(hi, 5)]}

    def gated(prob_col: str) -> dict:
        trades = []
        for r in oof:
            ts = r["frozen_at"].replace(" ", "T", 1)
            if ts.endswith("+00"):
                ts += ":00"
            d = evaluate(r[prob_col], yes_ask=r["yes_ask"], yes_bid=r["yes_bid"], frozen_at=ts)
            if d["action"] == "buy":
                trades.append({"frozen_at": r["frozen_at"],
                               "pnl": pnl(d["side"], d["cost"], r["outcome"])})
        return rule_stats(trades)

    g_raw, g_iso = gated("p_model"), gated("p_iso")
    improves = (
        scores["iso_model"]["brier"] < scores["raw_model"]["brier"]
        and diffs["iso_model"]["ci95"][1] < 0
        and scores["iso_model"]["brier"] <= scores["raw_market"]["brier"]
        and g_raw["n"] > 0 and g_iso["net_per_contract"] is not None
        and g_iso["net_per_contract"] >= g_raw["net_per_contract"]
        and g_iso["n"] >= 0.6 * g_raw["n"])
    return {"label": SERIES[key], "n_settled": len(rows), "n_oof": n_oof, "folds": fold_rows,
            "scores": scores, "paired_diffs": diffs,
            "gated": {"raw": g_raw, "iso": g_iso},
            "verdict": "improves" if improves else "does not improve",
            "curve_full_model": decile_curve([r["p_model"] for r in rows], [r["outcome"] for r in rows]),
            "curve_full_market": decile_curve([r["p_mkt"] for r in rows], [r["outcome"] for r in rows]),
            "curve_oof_raw": decile_curve([r["p_model"] for r in oof], [r["outcome"] for r in oof]),
            "curve_oof_iso": decile_curve([r["p_iso"] for r in oof], [r["outcome"] for r in oof]),
            "repro": repro,
            "oof": oof}


def main() -> None:
    out = {"frozen_at_utc": datetime.now(timezone.utc).isoformat(),
           "prereg_sha256": "1a2ecf81fd81466ccee2e72f3e83b16fe533ac8782a8abe341f323b7e8c1367c",
           "series": {}}
    for key in SERIES:
        rows = json.loads((HERE / "data" / f"{key}.json").read_text())
        for r in rows:  # the SQL CLI renders numeric columns as strings
            for col in ("p_model", "p_mkt", "yes_bid", "yes_ask", "elapsed_min", "sigma_1m"):
                r[col] = float(r[col])
            r["outcome"] = int(r["outcome"])
        res = run_series(key, rows)
        out["series"][key] = {k: v for k, v in res.items() if k != "oof"}
        (HERE / f"oof_{key}.json").write_text(json.dumps(res["oof"], indent=1))
        s, d, g = res["scores"], res["paired_diffs"], res["gated"]
        print(f"\n== {res['label']} == settled {res['n_settled']}, OOF {res['n_oof']}")
        for name in ("raw_model", "iso_model", "platt_model", "raw_market", "iso_market"):
            print(f"  {name:12s} brier {s[name]['brier']:.5f}  log {s[name]['logscore']:.5f}")
        for name, dd in d.items():
            print(f"  diff {name:12s} {dd['mean_diff']:+.5f}  CI [{dd['ci95'][0]:+.5f}, {dd['ci95'][1]:+.5f}]")
        print(f"  gated raw: n={g['raw']['n']} net={g['raw']['net_per_contract']} win={g['raw']['win_rate']} low95={g['raw']['low95']}")
        print(f"  gated iso: n={g['iso']['n']} net={g['iso']['net_per_contract']} win={g['iso']['win_rate']} low95={g['iso']['low95']}")
        print(f"  VERDICT: {res['verdict']}")
    (HERE / "results.json").write_text(json.dumps(out, indent=1))
    print("\nwrote results.json + oof_*.json")


if __name__ == "__main__":
    main()
