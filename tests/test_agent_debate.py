"""The debate feed (feed spec §8): schema tolerance, the mandatory labels, the fence,
grading math, the falsification banner, and stored failures."""
from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tradehub.agents import grader, importer, payload, runner, store
from tradehub.agents.schema import RunRecord

RAW = {
    "ticker": "pltr",
    "decision": "Buy",
    "framework_version": "0.2.3",
    "llm_provider": "anthropic",
    "llm_model": "claude-sonnet-4-5",
    "inputs_note": "framework defaults",
    "cost_usd": None,
    "final_state": {
        "market_report": "Technicals: uptrend.",
        "sentiment_report": "Sentiment: warm.",
        "news_report": "News: a contract win.",
        "fundamentals_report": "Fundamentals: revenue growing.",
        "investment_debate_state": {"bull_history": "Bull: growth. Bull closing: acceleration.",
                                    "bear_history": "Bear: valuation.",
                                    "judge_decision": "Research: Buy on growth."},
        "trader_investment_plan": "Trader: buy a starter position.",
        "risk_debate_state": {"judge_decision": "Risk: position small; approved."},
        "final_trade_decision": "**Rating**: Buy\n\n**Executive Summary**: growth wins.",
    },
}


@pytest.fixture
def agents_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEHUB_AGENTS_DIR", str(tmp_path))
    return tmp_path


def _record(raw=RAW, **kw) -> RunRecord:
    base = {"run_id": "pltr-20261101-090000", "run_at_ct": "2026-11-01T09:00:00-05:00",
            "run_at_utc": "2026-11-01T14:00:00+00:00", "as_of_date": "2026-10-30",
            "historical": False}
    base.update(kw)
    return importer.build_record(raw, **base)


def test_import_tolerates_missing_fields_and_marks_not_recorded(agents_dir):
    sparse = {"ticker": "XLE", "final_state": {}}
    rec = _record(sparse, run_id="xle-1", as_of_date="2026-10-30")
    assert rec.decision is None and rec.status == "partial"  # no readable rating = partial
    card = payload.card(rec, [], latest_session="2026-10-30")
    assert card["decision"] == "not recorded"
    assert card["analyst_summaries"]["fundamentals"] == "not recorded"
    assert card["cost_usd"] == "not recorded" and card["framework_version"] == "not recorded"


def test_labels_chip_stale_and_historical(agents_dir):
    rec = _record()
    fresh = payload.card(rec, [], latest_session="2026-11-02")  # 1 trading day later
    assert fresh["chip"] == "LLM agent debate — not a model signal"
    assert fresh["stale"] is False and fresh["decision"] == "Buy"
    stale = payload.card(rec, [], latest_session="2026-11-11")  # 8 trading days later
    assert stale["stale"] is True
    hist = payload.card(_record(historical=True), [], latest_session="2026-11-02")
    assert hist["historical_label"] == "historical run"
    grades = payload.card(rec, [], latest_session="2026-11-02")["grades"]
    assert grades == {"+5d": "pending", "+20d": "pending"}


def test_no_execution_imports():
    """The fence: importing the agents package pulls in no order/broker/portfolio module."""
    code = ("import sys; import tradehub.agents, tradehub.agents.runner, tradehub.agents.grader;"
            "bad = [m for m in sys.modules if 'alpaca' in m or 'paper_orders' in m"
            " or m.startswith('tradehub.portfolio')];"
            "assert not bad, bad")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(Path(__file__).resolve().parents[1]))
    assert proc.returncode == 0, proc.stderr


def _closes(path: list[float], start="2026-10-01") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(path))
    return pd.Series(path, index=idx)


def _run(decision: str, as_of: str, run_id="r1") -> RunRecord:
    return RunRecord(run_id=run_id, ticker="PLTR", run_at_ct="x", run_at_utc="x",
                     as_of_date=as_of, decision=decision, status="complete")


def test_grading_math_hit_miss_flat_and_no_call():
    idx = pd.bdate_range("2026-10-01", periods=40)
    as_of = str(idx[10].date())
    up = _closes([100.0] * 11 + [101.0, 102.0, 103.0, 104.0, 110.0] + [111.0] * 24)
    hit = grader.grade_run(_run("Buy", as_of), up, 5, graded_at="t")
    assert hit.outcome == "hit" and hit.ret_pct == pytest.approx(10.0)
    miss = grader.grade_run(_run("Sell", as_of), up, 5, graded_at="t")
    assert miss.outcome == "miss"
    flat = grader.grade_run(_run("Buy", as_of), _closes([100.0] * 40), 5, graded_at="t")
    assert flat.outcome == "miss" and flat.ret_pct == 0.0  # flat is a miss (§7)
    hold = grader.grade_run(_run("Hold", as_of), up, 5, graded_at="t")
    assert hold.outcome == "no-call"
    early = grader.grade_run(_run("Buy", as_of), up, 20, graded_at="t")
    assert early is not None
    assert grader.grade_run(_run("Buy", str(idx[38].date())), up, 5, graded_at="t") is None  # pending


def test_record_summary_and_falsification_banner():
    grades = []
    for i in range(30):
        grades.append(grader.GradeEntry(run_id=f"r{i}", horizon=5, ret_pct=1.0,
                                        outcome="hit" if i < 15 else "miss", graded_at="t"))
    summary = grader.record_summary(grades)
    assert summary["h5"] == {"graded": 30, "hits": 15, "hit_rate": 0.5, "no_calls": 0}
    assert summary["banner"] is True  # 30 graded, 50% -> no edge detected
    summary2 = grader.record_summary(grades[:29])
    assert summary2["banner"] is False


def test_runner_stores_failure_when_framework_missing(agents_dir, monkeypatch):
    monkeypatch.delenv("TRADEHUB_AGENTS_PYTHON", raising=False)
    monkeypatch.setattr(runner, "framework_python", lambda: None)
    rec = runner.run_debate("PLTR", "2026-10-30", now=datetime(2026, 11, 1, tzinfo=UTC),
                            latest_session="2026-10-30")
    assert rec.status == "failed_error" and "not installed" in (rec.error or "")
    assert [r.run_id for r in store.list_runs()] == [rec.run_id]  # stored, not dropped
    assert store.read_report(rec.run_id) is not None


def test_runner_imports_a_fake_frameworks_output(agents_dir, tmp_path, monkeypatch):
    fake = tmp_path / "fake_python.py"
    fake.write_text("import json, sys\nprint(json.dumps(" + repr(RAW) + "))\n")
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    monkeypatch.setattr(runner, "_RUNNER", fake)
    rec = runner.run_debate("PLTR", "2026-10-30", now=datetime(2026, 11, 1, tzinfo=UTC),
                            latest_session="2026-10-30",
                            spawn=lambda cmd, **kw: subprocess.run([sys.executable, str(fake)],
                                                                   capture_output=True, text=True))
    assert rec.status == "complete" and rec.decision == "Buy" and rec.ticker == "PLTR"
    report = store.read_report(rec.run_id)
    assert report is not None and "Bull case" in report and "Risk verdict" in report


def test_api_feed_is_labelled(agents_dir):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    rec = _record()
    store.save_run(rec, "# report\n")
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k@example.com",
                                                                  "is_admin": True}
    client = TestClient(main.app)
    body = client.get("/api/agent-debates").json()
    assert body["chip"] == "LLM agent debate — not a model signal"
    assert body["cards"][0]["ticker"] == "PLTR" and body["cards"][0]["source"] == "agent_debate"
    assert client.get(f"/api/agent-debates/{rec.run_id}/report").status_code == 200
    assert client.get("/api/agent-debates/nope/report").status_code == 404
