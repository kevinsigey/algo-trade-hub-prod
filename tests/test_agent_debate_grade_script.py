"""A6 (2026-11-11): the agent-debate +5d/+20d grades due Nov 9 never ran
because `grader.grade_all` had exactly one caller -- the manual operator
CLI (`agent_debate grade`). No cron, route, or hook invoked it, so grading
depended on a human remembering. The fix is a scheduled entrypoint,
`tradehub.scripts.agent_debate_grade`, that the nightly cron runs; these
tests pin that the entrypoint grades every due run end to end and is
idempotent."""
import pandas as pd
import pytest

from tradehub.agents import store
from tradehub.agents.schema import RunRecord
from tradehub.scripts import agent_debate_grade


@pytest.fixture
def agents_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_AGENTS_DIR", str(tmp_path))
    return tmp_path


def _closes() -> pd.Series:
    idx = pd.bdate_range("2026-10-01", periods=40)
    return pd.Series([100.0] * 11 + [110.0] * 29, index=idx)


def _save_due_run():
    idx = pd.bdate_range("2026-10-01", periods=40)
    rec = RunRecord(run_id="pltr-20261015-090000", ticker="PLTR",
                    run_at_ct="x", run_at_utc="x",
                    as_of_date=str(idx[10].date()), decision="Buy",
                    status="complete")
    store.save_run(rec, None)
    return rec


def test_entrypoint_grades_every_due_horizon(agents_dir):
    _save_due_run()
    out = agent_debate_grade.grade(closes_fn=lambda ticker: _closes())
    graded = {(g["run_id"], g["horizon"]) for g in out["graded"]}
    assert graded == {("pltr-20261015-090000", 5),
                      ("pltr-20261015-090000", 20)}
    stored = store.load_grades()
    assert {(g.run_id, g.horizon) for g in stored} == graded
    assert all(g.outcome == "hit" for g in stored)  # Buy, +10% at both
    assert out["record"]["h5"]["graded"] == 1


def test_entrypoint_is_idempotent(agents_dir):
    _save_due_run()
    agent_debate_grade.grade(closes_fn=lambda ticker: _closes())
    out = agent_debate_grade.grade(closes_fn=lambda ticker: _closes())
    assert out["graded"] == []
    assert len(store.load_grades()) == 2


def test_entrypoint_leaves_a_not_yet_due_run_pending(agents_dir):
    idx = pd.bdate_range("2026-10-01", periods=40)
    rec = RunRecord(run_id="pltr-late", ticker="PLTR", run_at_ct="x",
                    run_at_utc="x", as_of_date=str(idx[38].date()),
                    decision="Buy", status="complete")
    store.save_run(rec, None)
    out = agent_debate_grade.grade(closes_fn=lambda ticker: _closes())
    assert out["graded"] == []
    assert store.load_grades() == []
