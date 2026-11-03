"""PASS rigor (Kevin, 2026-11-03): 42 of 53 ideas held a PASS under a bar
that only counted each idea's own reruns, and walk-forward folds were
computed but ignored. The standard now: a PASS must hold on unseen years,
clear a hub-wide FDR bar over every idea's current test, and hold in at
least half the walk-forward folds. Agent-gate attempts count per spec, so
re-rolling the gate tightens its bar instead of resetting it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradehub.workshop import registry
from tradehub.workshop.engine import verdict_of

_IDX = pd.bdate_range("2020-01-02", "2026-11-02")


def _frame(tickers, start):
    rng = np.random.default_rng(0)
    return pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0002, 0.01, len(_IDX))) for t in tickers},
                        index=_IDX)


def test_verdict_requires_walk_forward_in_half_the_folds():
    assert verdict_of(True, 0.001, 0.05, {"held": 2, "of": 4}) == "PASS"
    assert verdict_of(True, 0.001, 0.05, {"held": 4, "of": 4}) == "PASS"
    assert verdict_of(True, 0.001, 0.05, {"held": 1, "of": 4}) == "FAIL"
    assert verdict_of(True, 0.001, 0.05, {"held": 0, "of": 4}) == "FAIL"


def test_verdict_without_walk_forward_folds_cannot_pass():
    # No judged folds means the claim's durability is unverifiable, not fine.
    assert verdict_of(True, 0.001, 0.05, {"held": 0, "of": 0}) == "FAIL"
    assert verdict_of(True, 0.001, 0.05, None) == "PASS"  # legacy callers (events)


def _run(verdict, p, held=None, of=None):
    wf = None if held is None else {"held": held, "of": of}
    return {"verdict": verdict,
            "result": {"shuffle": {"p": p} if p is not None else None, "walk_forward": wf}}


def test_adjusted_applies_fdr_and_walk_forward():
    latest = {
        1: _run("PASS", 0.001, 4, 4),   # clears everything
        2: _run("PASS", 0.048, 4, 4),   # dies on the FDR bar
        3: _run("PASS", 0.001, 1, 4),   # clears FDR, dies on walk-forward
        4: _run("FAIL", 0.20, 4, 4),    # never passed
        5: _run("NOT ENOUGH DATA", None),
    }
    out = registry.adjusted(latest)
    assert out[1]["verdict_now"] == "PASS"
    assert out[2]["verdict_now"] != "PASS" and out[2]["fdr_pass"] is False
    assert out[3]["verdict_now"] != "PASS" and out[3]["fdr_pass"] is True and out[3]["wf_ok"] is False
    assert out[4]["verdict_now"] == "FAIL"
    assert out[5]["verdict_now"] == "NOT ENOUGH DATA"


def test_families_group_ideas_sharing_tickers():
    fams = registry.families({47: {"TXN", "MU"}, 51: {"MU", "TXN", "TSM"}, 54: {"MU"},
                              50: {"NVDA"}, 9: {"XLE"}})
    assert fams[47]["key"] == fams[51]["key"] == fams[54]["key"]
    assert fams[47]["size"] == 3 and "MU" in fams[47]["tickers"]
    assert fams[50]["size"] == 1 and fams[9]["size"] == 1


def test_origin_classification():
    lab = {"id": 47, "title": "Texas Instruments + Micron",
           "plain_words": "Lab3 wrap: TXN,MU — Random Lab Gen 3 (Nov 2026). Random Lab Gen 3 trial 54."}
    sweep = {"id": 16, "title": "SPY covered call", "plain_words": "SPY covered call — sweep survivor (Nov 2026)"}
    plain = {"id": 7, "title": "Ballast sleeve", "plain_words": "Ballast sleeve: hold XLV, XLP, XLU and MA"}
    assert registry.origin_of(lab, set()) == "lab"
    assert registry.origin_of(sweep, set()) == "lab"
    assert registry.origin_of(plain, set()) == "manual"
    assert registry.origin_of(plain, {7}) == "screen"
    assert registry.hindsight_selected("lab") and registry.hindsight_selected("screen")
    assert not registry.hindsight_selected("manual")
