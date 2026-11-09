"""The overlay battery (spec 2026-11-08, claim-typed gates amendment): the
verdict for a hedge / drawdown sleeve, graded only in combination.

A sleeve's standalone return is not its claim — ballast that "beats the
benchmark" on its own is just an allocation wearing a hedge's clothes. The
claim is what happens to the portfolio it bolts onto: here, the run's
benchmark blended with the sleeve at a frozen weight, over identical spans.
The combined series is built once, from the two return series — the idea's
already net of house costs, the benchmark costless, as everywhere in the
core — so nothing is double-counted and the sleeve is never judged alone.

Frozen constants (preregistered in the spec; changing them is a new
preregistration, not an edit):

- SLEEVE_WEIGHT 0.20: a sleeve is a minority allocation — a fifth of the book
  is the smallest share at which protection is measurable at portfolio scale,
  and the largest that leaves the host dominant.
- DD_MARGIN_PP 3.0: per span, the combined portfolio's worst fall must be at
  least 3 points shallower than the host's alone.
- DD_MIN_HOST_PP 5.0: below a 5-point host drawdown there was no fall to
  protect against (the basket battery's convention); the leg is recorded
  not-binding and does not gate.
- SHARPE_TOLERANCE 0.05: the combined Sharpe may trail the host's by at most
  a twentieth — protection may not be bought with a worse ride.
- RETURN_BUDGET_PP 2.0: the combined CAGR may trail the host's by at most
  2 points a year — the most return the sleeve may give back.

Pure: daily return arrays in, a battery dict out. The engine owns the frame,
the spans and the result shape; this module owns the measurement.
"""

from __future__ import annotations

import math

import numpy as np

DAYS = 252
SLEEVE_WEIGHT = 0.20
DD_MARGIN_PP = 3.0
DD_MIN_HOST_PP = 5.0
SHARPE_TOLERANCE = 0.05
RETURN_BUDGET_PP = 2.0


def _cagr(r: np.ndarray) -> float:
    if len(r) == 0:
        return math.nan
    growth = float(np.prod(1 + r))
    return (growth ** (DAYS / len(r)) - 1) * 100 if growth > 0 else -100.0


def _max_dd(r: np.ndarray) -> float:
    """Worst peak-to-trough fall, in percent, <= 0 — the engine's own convention."""
    if not len(r):
        return math.nan
    wealth = np.cumprod(1 + r)
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1) * 100)


def _sharpe(r: np.ndarray) -> float:
    """Annualized Sharpe of a daily return series (the house convention: a
    varianceless series has Sharpe 0 at mean 0, signed infinity otherwise)."""
    if len(r) < 2:
        return math.nan
    sd = float(np.std(r, ddof=1))
    if sd == 0.0:
        mean = float(np.mean(r))
        return 0.0 if mean == 0.0 else math.copysign(math.inf, mean)
    return float(np.mean(r) / sd * math.sqrt(DAYS))


def span_stats(r: np.ndarray, b: np.ndarray, *, weight: float = SLEEVE_WEIGHT) -> dict:
    """One span of the host alone vs the host blended with the sleeve."""
    c = (1 - weight) * b + weight * r
    host = {"sharpe": float(_sharpe(b)), "max_dd": float(_max_dd(b)), "cagr": float(_cagr(b))}
    comb = {"sharpe": float(_sharpe(c)), "max_dd": float(_max_dd(c)), "cagr": float(_cagr(c))}
    binding = bool(math.isfinite(host["max_dd"]) and abs(host["max_dd"]) >= DD_MIN_HOST_PP)
    margin = float(abs(host["max_dd"]) - abs(comb["max_dd"]))
    return {"days": int(len(r)), "weight": weight, "host": host, "combined": comb,
            "dd_margin": margin, "dd_binding": binding,
            "dd_holds": bool(margin >= DD_MARGIN_PP) if binding else True,
            "sharpe_delta": float(comb["sharpe"] - host["sharpe"]),
            "sharpe_holds": bool(comb["sharpe"] >= host["sharpe"] - SHARPE_TOLERANCE),
            "cagr_giveback": float(host["cagr"] - comb["cagr"]),
            "budget_holds": bool(host["cagr"] - comb["cagr"] <= RETURN_BUDGET_PP)}


def battery(r: np.ndarray, b: np.ndarray, *, split: int) -> dict:
    """The overlay verdict over both spans: every binding leg must hold on each."""
    spans: dict[str, dict] = {}
    legs: list[dict] = []
    for name, sl in (("built", slice(0, split)), ("unseen", slice(split, len(r)))):
        st = span_stats(r[sl], b[sl])
        spans[name] = st
        dd_detail = (f"combined worst fall {st['combined']['max_dd']:.1f}% vs host {st['host']['max_dd']:.1f}%: "
                     f"margin {st['dd_margin']:.1f} pts must reach {DD_MARGIN_PP}" if st["dd_binding"] else
                     f"not binding: the host fell only {st['host']['max_dd']:.1f}% on this span")
        legs.append({"name": f"dd_{name}", "holds": bool(st["dd_holds"]), "detail": dd_detail})
        legs.append({"name": f"sharpe_{name}", "holds": bool(st["sharpe_holds"]),
                     "detail": f"combined Sharpe {st['combined']['sharpe']:.2f} vs host "
                               f"{st['host']['sharpe']:.2f}: may trail by at most {SHARPE_TOLERANCE}"})
        legs.append({"name": f"budget_{name}", "holds": bool(st["budget_holds"]),
                     "detail": f"combined CAGR {st['combined']['cagr']:.1f}% vs host {st['host']['cagr']:.1f}%: "
                               f"give-back {st['cagr_giveback']:.1f} pts/yr must stay within {RETURN_BUDGET_PP}"})
    return {"type": "overlay",
            "constants": {"sleeve_weight": SLEEVE_WEIGHT, "dd_margin_pp": DD_MARGIN_PP,
                          "dd_min_host_pp": DD_MIN_HOST_PP, "sharpe_tolerance": SHARPE_TOLERANCE,
                          "return_budget_pp": RETURN_BUDGET_PP},
            "spans": spans, "p": None, "legs": legs,
            "verdict": "PASS" if all(leg["holds"] for leg in legs) else "FAIL"}
