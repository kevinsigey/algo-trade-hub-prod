"""The event battery (spec 2026-11-08, amendment): per-event excess vs the index
(judged) and vs matched in-study peers (reported), cross-event t and hit rate per
span, frozen minimum event counts. The battery rides inside run_event_test's
result; the run's own verdict stays the existing event gate's."""

import numpy as np
import pandas as pd
import pytest

from tradehub.workshop import event_gate, events
from tradehub.workshop.events import EventSpec, run_event_test


def _series(mean, sd, n, seed):
    return np.random.default_rng(seed).normal(mean, sd, n)


# ── the battery on raw per-event arrays ──────────────────────────────────────

def test_battery_passes_a_consistent_drift():
    idx = np.concatenate([_series(1.0, 1.5, 30, 1), _series(1.2, 1.5, 15, 2)])
    out = event_gate.battery(idx, None, split=30)
    assert out["type"] == "event" and out["verdict"] == "PASS", out["legs"]
    u = out["spans"]["unseen"]["index"]
    assert u["n"] == 15 and u["t"] >= 2.0 and u["hit"] >= 0.55
    assert out["spans"]["unseen"]["peer"] is None  # no peers given: reported as n/a
    assert out["p"] < 0.05


def test_battery_fails_when_unseen_events_are_noise():
    idx = np.concatenate([_series(1.0, 1.5, 30, 3), _series(0.3, 3.0, 15, 4)])
    out = event_gate.battery(idx, None, split=30)
    assert out["verdict"] == "FAIL"
    legs = {leg["name"]: leg for leg in out["legs"]}
    assert legs["t_unseen"]["holds"] is False


def test_battery_fails_on_hit_rate_even_with_a_significant_mean():
    # A few huge wins carry the mean (t clears 2.0) but most events lose: the hit leg bites.
    unseen = np.array([5.0] * 8 + [-0.5] * 12)
    idx = np.concatenate([_series(1.0, 1.5, 30, 5), unseen])
    out = event_gate.battery(idx, None, split=30)
    u = out["spans"]["unseen"]["index"]
    assert u["t"] >= 2.0 and u["hit"] == pytest.approx(0.4)
    assert out["verdict"] == "FAIL"
    legs = {leg["name"]: leg for leg in out["legs"]}
    assert legs["hit_unseen"]["holds"] is False and legs["t_unseen"]["holds"] is True


def test_battery_fails_when_the_built_span_points_the_other_way():
    idx = np.concatenate([_series(-1.0, 1.5, 30, 6), _series(1.2, 1.5, 15, 7)])
    out = event_gate.battery(idx, None, split=30)
    assert out["verdict"] == "FAIL"
    legs = {leg["name"]: leg for leg in out["legs"]}
    assert legs["built_direction"]["holds"] is False


def test_battery_needs_minimum_event_counts():
    few = event_gate.battery(_series(1.0, 1.0, 19, 8), None, split=10)
    assert few["verdict"] == "NOT ENOUGH DATA"
    thin_unseen = event_gate.battery(_series(1.0, 1.0, 40, 9), None, split=31)  # 9 unseen < 10
    assert thin_unseen["verdict"] == "NOT ENOUGH DATA"


def test_battery_reports_the_peer_control():
    idx = np.concatenate([_series(1.0, 1.5, 30, 10), _series(1.2, 1.5, 15, 11)])
    peer = idx - 0.4  # the names beat their in-study peers by less than they beat the index
    out = event_gate.battery(idx, peer, split=30)
    p = out["spans"]["unseen"]["peer"]
    assert p is not None and p["n"] == 15 and p["mean"] == pytest.approx(0.8, abs=0.35)
    assert out["verdict"] == "PASS"  # peers are a reported control, never a verdict leg


def test_event_constants_match_the_event_engines():
    # Adopted, not reinvented: the battery's minimums are events.py's own frozen numbers,
    # pinned together so the two can never drift apart silently.
    assert event_gate.MIN_EVENTS == events.MIN_EVENTS == 20
    assert event_gate.MIN_UNSEEN_EVENTS == events.MIN_UNSEEN_EVENTS == 10


# ── the battery rides in run_event_test, the gate's verdict untouched ────────

def _closes(seed=12, n=2200):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-02", periods=n)
    spy = rng.normal(0.0003, 0.01, n)
    aaa = spy + rng.normal(0, 0.004, n)
    return rng, idx, spy, aaa


def _plant_drift(aaa, idx, event_days, rng):
    """+1%/day on AAA for days +1..+5 after each event day: a clean drift_1_5 signal."""
    out = aaa.copy()
    pos = {d: i for i, d in enumerate(idx)}
    for d in event_days:
        i = pos[d]
        out[i + 1:i + 6] += 0.01
    return out


def _custom_spec(days, tickers=("AAA",)):
    return EventSpec.model_validate({
        "title": "Planted drift study", "tickers": list(tickers), "event": "custom",
        "custom": [{"ticker": t, "date": str(d.date())} for t in tickers for d in days],
        "window": "drift_1_5", "direction": "up", "benchmark": "SPY",
        "start": "2018-01-02", "unseen_fraction": 0.3})


def test_event_run_carries_the_battery_beside_the_gate_verdict():
    rng, idx, spy, aaa = _closes()
    days = list(idx[100:2100:50])  # 40 events spread over both spans
    aaa = _plant_drift(aaa, idx, days, rng)
    closes = pd.DataFrame({"SPY": 100 * np.cumprod(1 + spy), "AAA": 100 * np.cumprod(1 + aaa)}, index=idx)
    out = run_event_test(_custom_spec(days), closes, {}, variations=1, seed=7)
    bat = out["battery"]
    assert bat["type"] == "event" and bat["verdict"] == "PASS", bat["legs"]
    assert bat["spans"]["unseen"]["index"]["mean"] > 3  # ~+5% planted, minus noise
    assert out["verdict"] == "PASS" and out["shuffle"] is not None  # the gate's own read, intact
    assert bat["spans"]["unseen"]["peer"] is None  # single-name study: no in-study peers


def test_event_run_reports_peers_for_a_multi_name_study():
    rng, idx, spy, aaa = _closes()
    bbb = spy + rng.normal(0, 0.004, len(idx))
    days = list(idx[100:2100:50])
    aaa = _plant_drift(aaa, idx, days, rng)  # only AAA drifts; BBB is its peer control
    closes = pd.DataFrame({"SPY": 100 * np.cumprod(1 + spy), "AAA": 100 * np.cumprod(1 + aaa),
                           "BBB": 100 * np.cumprod(1 + bbb)}, index=idx)
    out = run_event_test(_custom_spec(days, tickers=("AAA", "BBB")), closes, {}, variations=1, seed=7)
    peer = out["battery"]["spans"]["unseen"]["peer"]
    assert peer is not None and peer["n"] > 0


def test_event_run_too_few_events_still_carries_the_battery():
    rng, idx, spy, aaa = _closes()
    days = list(idx[100:600:100])  # 5 events: below every minimum
    closes = pd.DataFrame({"SPY": 100 * np.cumprod(1 + spy), "AAA": 100 * np.cumprod(1 + aaa)}, index=idx)
    out = run_event_test(_custom_spec(days), closes, {}, variations=1, seed=7)
    assert out["verdict"] == "NOT ENOUGH DATA"
    assert out["battery"]["type"] == "event" and out["battery"]["verdict"] == "NOT ENOUGH DATA"
