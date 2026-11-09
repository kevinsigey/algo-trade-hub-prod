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
    assert verdict_of(True, 0.001, 0.05, {"held": 3, "of": 4}) == "PASS"
    assert verdict_of(True, 0.001, 0.05, {"held": 2, "of": 4}) == "FAIL"  # Kevin's bar, 2026-11-03: 3 of 4
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


def test_p_must_be_at_or_under_one_percent():
    assert verdict_of(True, 0.01, 0.05, {"held": 4, "of": 4}) == "PASS"
    assert verdict_of(True, 0.011, 0.05, {"held": 4, "of": 4}) == "FAIL"
    assert verdict_of(True, 0.011, 0.05, None) == "PASS"  # event studies keep their own bar


def test_adjusted_demotes_a_p_over_the_bar_and_says_which_rule():
    latest = {1: _run("PASS", 0.001, 4, 4), 2: _run("PASS", 0.02, 4, 4), 3: _run("PASS", 0.001, 2, 4)}
    out = registry.adjusted(latest)
    assert out[1]["verdict_now"] == "PASS" and out[1]["p_ok"] is True
    assert out[2]["verdict_now"] == "FAIL" and out[2]["p_ok"] is False and out[2]["fdr_pass"] is True
    assert out[3]["verdict_now"] == "FAIL" and out[3]["wf_ok"] is False


def test_a_new_stricter_verdict_changes_no_stored_verdict():
    run = _run("PASS", 0.02, 4, 4)
    registry.adjusted({1: run})
    assert run["verdict"] == "PASS"


# ── event runs after the battery's promotion (spec 2026-11-08, Amendment 2) ──

def _event_run(verdict, battery_p, shuffle_p=None):
    """A run row in one of the two event shapes: post-promotion (the battery
    judged; its record carries the p, the legacy gate is a control whose
    numbers are not at top level) or pre-promotion (no battery block; the
    verdict was the shuffle's)."""
    result = {"kind": "event", "walk_forward": None,
              "shuffle": {"p": shuffle_p} if shuffle_p is not None else None}
    if battery_p is not None or shuffle_p is None:
        result["battery"] = {"type": "event", "p": battery_p}
    return {"verdict": verdict, "result": result}


def test_event_runs_answer_to_the_battery_p_in_the_family():
    latest = {1: _run("PASS", 0.001, 4, 4),        # a timing anchor for the family
              2: _event_run("PASS", 0.048)}         # the battery's p, over the 0.01 bar
    out = registry.adjusted(latest)
    assert out[2]["p"] == 0.048 and out[2]["p_ok"] is False
    assert out[2]["verdict_now"] == "FAIL"  # demoted on its own judge's p


def test_event_run_with_a_strong_battery_p_keeps_its_p():
    out = registry.adjusted({1: _event_run("PASS", 0.001)})
    assert out[1]["p"] == 0.001 and out[1]["p_ok"] is True and out[1]["fdr_pass"] is True


def test_prepromotion_event_run_keeps_its_shuffle_p():
    # Stored before the battery existed: no battery block, the verdict was the
    # shuffle's, so the shuffle's p is still its honest family accounting.
    out = registry.adjusted({1: _event_run("PASS", None, shuffle_p=0.001)})
    assert out[1]["p"] == 0.001 and out[1]["p_ok"] is True


def test_event_battery_nodata_stays_out_of_the_family():
    out = registry.adjusted({1: _event_run("NOT ENOUGH DATA", None)})
    assert out[1]["p"] is None and out[1]["verdict_now"] == "NOT ENOUGH DATA"
