"""Thesis tracker PR 4: the grader run against a fake store.

The run grades every due print's graded card (latest pre-print card;
superseded cards never grade), writes an outcome only when every
horizon is computable, refreshes the Claim A/C falsifier states from
the frozen thresholds, and stamps tracker_health either way -- the
stamp is what the sizing fork reads, so a run that grades nothing
still has to land it.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from tradehub.tracker import grader
from tests.test_tracker_grading import SPY, TICKER
from tests.test_valuation_verdicts import FakeClient

PRINT = "2026-11-20T21:00:00Z"
NOW = datetime(2026, 12, 2, 22, 30, tzinfo=timezone.utc)


def _seeded() -> FakeClient:
    c = FakeClient()
    c.tables["theses"] = [
        {"id": 1, "slug": "event-lab", "title": "Event lab (T1 rebuilt)",
         "sleeve": "event_lab", "status": "live", "kill_lines": [],
         "spec_ref": None}]
    c.tables["thesis_falsifiers"] = [
        {"id": 11, "thesis_id": 1, "claim": "A",
         "metric": "classification_separation",
         "threshold": {"min_separation": 0.60, "demote_below": 0.60,
                       "kill_below_rolling": 0.50},
         "window_spec": {"prints": 40, "rolling_kill_prints": 60},
         "deadline": "2027-03-01", "state": "armed"},
        {"id": 12, "thesis_id": 1, "claim": "C",
         "metric": "play_kind_a_net_after_costs",
         "threshold": {"must_net_positive": True},
         "window_spec": {"fires": 5},
         "deadline": "2027-03-01", "state": "armed"},
    ]
    c.tables["tracker_health"] = [
        {"id": 1, "last_grader_run_at": None, "last_grader_ok": False}]
    c.tables["forecast_cards"] = []
    c.tables["forecast_outcomes"] = []
    return c


def _card(c: FakeClient, *, cid: int, frozen: str, **over):
    row = {"id": cid, "ticker": "NVDA", "thesis_id": 1, "print_at": PRINT,
           "whisper_esp": 0.04, "whisper_sign": "positive",
           "money_flow_direction": "inflow",
           "money_flow_evidence": [{"text": "capex raised",
                                    "source": "https://example.com/x"}],
           "guide_position": "below", "predicted_direction": "up",
           "opposing_case_ref": "research/nvda.md#opposing-case",
           "classification": "improved", "supersedes_id": None,
           "frozen_at": frozen}
    row.update(over)
    c.tables["forecast_cards"].append(row)
    return row


def _bars(symbol, _start, end):
    series = TICKER if symbol == "NVDA" else SPY
    return [(d, close) for d, close in series if d <= end]


def test_a_due_print_grades_and_stamps_health():
    c = _seeded()
    _card(c, cid=1, frozen="2026-11-20T12:00:00Z")
    out = grader.grade_run(c, _bars, NOW)
    assert out["graded"] == 1 and out["waiting"] == 0
    rows = c.tables["forecast_outcomes"]
    assert len(rows) == 1 and rows[0]["card_id"] == 1
    assert abs(rows[0]["ret_1d"] - 0.10) < 1e-12
    assert rows[0]["classification_hit"] is True
    health = c.tables["tracker_health"][0]
    assert health["last_grader_ok"] is True
    assert health["last_grader_run_at"] == NOW.isoformat()


def test_an_already_graded_print_is_not_regraded():
    c = _seeded()
    _card(c, cid=1, frozen="2026-11-20T12:00:00Z")
    grader.grade_run(c, _bars, NOW)
    out = grader.grade_run(c, _bars, NOW)
    assert out["graded"] == 0 and len(c.tables["forecast_outcomes"]) == 1


def test_only_the_latest_preprint_card_grades():
    c = _seeded()
    _card(c, cid=1, frozen="2026-11-19T12:00:00Z",
          classification="deteriorated")
    _card(c, cid=2, frozen="2026-11-20T12:00:00Z", supersedes_id=1)
    out = grader.grade_run(c, _bars, NOW)
    assert out["graded"] == 1
    row = c.tables["forecast_outcomes"][0]
    assert row["card_id"] == 2 and row["classification_hit"] is True


def test_a_print_whose_horizons_have_not_arrived_waits():
    c = _seeded()
    _card(c, cid=1, frozen="2026-11-20T12:00:00Z")
    early = datetime(2026, 11, 24, 22, 30, tzinfo=timezone.utc)
    out = grader.grade_run(c, _bars, early)
    assert out["graded"] == 0 and out["waiting"] == 1
    assert c.tables["forecast_outcomes"] == []
    # ...but the health stamp still lands: the grader ran fine.
    assert c.tables["tracker_health"][0]["last_grader_ok"] is True


def test_a_future_print_is_not_due():
    c = _seeded()
    _card(c, cid=1, frozen="2026-11-20T12:00:00Z",
          print_at="2026-12-20T21:00:00Z")
    out = grader.grade_run(c, _bars, NOW)
    assert out["graded"] == 0 and out["waiting"] == 0


def test_claim_a_state_flips_when_the_window_completes():
    c = _seeded()
    for i in range(40):
        c.tables["forecast_cards"].append(
            {"id": 100 + i, "ticker": "NVDA", "thesis_id": 1,
             "print_at": PRINT, "classification": "improved",
             "frozen_at": "2026-11-20T12:00:00Z"})
        c.tables["forecast_outcomes"].append(
            {"id": 200 + i, "card_id": 100 + i,
             "classification_hit": i < 24})       # exactly 60%
    progress = grader.refresh_claim_states(c, [])
    assert progress["A"]["verdict"] == "passed"
    states = {r["claim"]: r["state"] for r in c.tables["thesis_falsifiers"]}
    assert states["A"] == "passed" and states["C"] == "armed"


def test_claim_c_state_flips_on_the_first_five_fires():
    c = _seeded()
    progress = grader.refresh_claim_states(
        c, [100.0, -50.0, 25.0, -10.0, -5.0])    # net +60 over five
    assert progress["C"]["verdict"] == "passed"
    states = {r["claim"]: r["state"] for r in c.tables["thesis_falsifiers"]}
    assert states["C"] == "passed"
    c2 = _seeded()
    grader.refresh_claim_states(c2, [-1.0] * 5)
    states = {r["claim"]: r["state"] for r in c2.tables["thesis_falsifiers"]}
    assert states["C"] == "fired"


def test_a_fired_claim_is_not_reopened_by_later_rows():
    c = _seeded()
    c.tables["thesis_falsifiers"][0]["state"] = "fired"
    grader.refresh_claim_states(c, [])
    assert c.tables["thesis_falsifiers"][0]["state"] == "fired"


def test_stamp_health_records_a_failed_run():
    c = _seeded()
    grader.stamp_health(c, NOW, ok=False)
    health = c.tables["tracker_health"][0]
    assert health["last_grader_ok"] is False
    assert health["last_grader_run_at"] == NOW.isoformat()
