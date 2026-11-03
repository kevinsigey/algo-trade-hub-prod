"""The debate feed (feed spec §8): schema tolerance, the mandatory labels, the fence,
grading math, the falsification banner, and stored failures."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from tradehub.agents import grader, importer, payload, runner, store
from tradehub.agents.schema import GradeEntry, RunRecord

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
    # No network in tests: the market anchor is a separate test's subject.
    monkeypatch.setattr(runner, "market_anchor", lambda ticker, now=None: None)
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


def _fail_spawn(stderr):
    def spawn(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr)
    return spawn


def test_runner_stores_the_root_cause_not_the_langgraph_wrapper(agents_dir, monkeypatch):
    # The real failure shape (2026-11-02): the deepest exception is the cause;
    # the traceback's last line only names the stage that was running.
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    stderr = ("Traceback (most recent call last):\n"
              "  File \"x.py\", line 1, in <module>\n"
              "ValueError: yahoo finance returned no news for the ticker\n"
              "During task with name 'News Analyst' and id 'abc-123'\n")
    rec = runner.run_debate("GOOGL", "2026-11-02", now=datetime(2026, 11, 2, tzinfo=UTC),
                            latest_session="2026-11-02", spawn=_fail_spawn(stderr))
    assert rec.status == "failed_error"
    assert "ValueError: yahoo finance returned no news" in (rec.error or "")
    assert "During task" not in (rec.error or "")


def test_runner_names_quota_exhaustion_plainly(agents_dir, monkeypatch):
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    stderr = ("langchain_google_genai.chat_models.GoogleRateLimitError: Error calling model "
              "'gemini-3.8-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. quota exceeded "
              "for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests\n"
              "During task with name 'News Analyst' and id 'abc-123'\n")
    rec = runner.run_debate("NVDA", "2026-11-02", now=datetime(2026, 11, 2, tzinfo=UTC),
                            latest_session="2026-11-02", spawn=_fail_spawn(stderr))
    assert rec.status == "failed_error"
    assert "quota exhausted" in (rec.error or "") and "20 requests/day" in (rec.error or "")


_QUOTA_STDERR = ("langchain_google_genai.chat_models.GoogleRateLimitError: Error calling model "
                 "'gemini-3.8-flash' (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED\n"
                 "During task with name 'News Analyst' and id 'abc-123'\n")


def test_runner_falls_back_to_openrouter_on_quota(agents_dir, monkeypatch):
    # Kevin's rule (2026-11-02): when Google is down, debates keep going on a
    # free OpenRouter REASONING model instead of dying with the daily quota.
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.delenv("TRADEHUB_AGENTS_PROVIDER", raising=False)
    calls = []

    def spawn(cmd, **kw):
        calls.append(kw.get("env") or {})
        if (kw.get("env") or {}).get("TRADEHUB_AGENTS_BACKEND_URL"):
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(RAW), stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=_QUOTA_STDERR)

    rec = runner.run_debate("NVDA", "2026-11-02", now=datetime(2026, 11, 2, tzinfo=UTC),
                            latest_session="2026-11-02", spawn=spawn)
    assert rec.status == "complete" and len(calls) == 2
    fb = calls[1]
    assert fb["TRADEHUB_AGENTS_PROVIDER"] == "openai"
    assert fb["TRADEHUB_AGENTS_BACKEND_URL"] == "https://openrouter.ai/api/v1"
    assert fb["OPENAI_API_KEY"] == "or-test-key"
    assert fb["TRADEHUB_AGENTS_MODEL"].endswith(":free")


def test_runner_reports_both_failures_when_fallback_also_fails(agents_dir, monkeypatch):
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    rec = runner.run_debate("NVDA", "2026-11-02", now=datetime(2026, 11, 2, tzinfo=UTC),
                            latest_session="2026-11-02", spawn=_fail_spawn(_QUOTA_STDERR))
    assert rec.status == "failed_error"
    assert "quota exhausted" in (rec.error or "") and "fallback also failed" in (rec.error or "")


def test_runner_does_not_fallback_for_a_debate_failure(agents_dir, monkeypatch):
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    calls = []

    def spawn(cmd, **kw):
        calls.append(kw)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ValueError: no news for the ticker\n")

    rec = runner.run_debate("NVDA", "2026-11-02", now=datetime(2026, 11, 2, tzinfo=UTC),
                            latest_session="2026-11-02", spawn=spawn)
    assert rec.status == "failed_error" and len(calls) == 1
    assert "ValueError: no news" in (rec.error or "")


def test_api_run_starts_one_debate_per_ticker(agents_dir, monkeypatch):
    import threading as th
    import time

    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    gate = th.Event()
    calls: list[str] = []

    def fake_run(ticker, latest_session=None):
        calls.append(ticker)
        gate.wait(5)

    monkeypatch.setattr(runner, "run_debate", fake_run)
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k@example.com",
                                                                  "is_admin": True}
    client = TestClient(main.app)
    r = client.post("/api/agent-debates/run", json={"ticker": "nvda"})
    assert r.status_code == 202 and r.json() == {"started": "NVDA"}
    assert client.post("/api/agent-debates/run", json={"ticker": "NVDA"}).status_code == 409
    assert client.post("/api/agent-debates/run", json={"ticker": "not a ticker!"}).status_code == 422
    gate.set()
    for _ in range(50):  # the background thread finishes and frees the ticker
        if calls == ["NVDA"] and not main._DEBATE_IN_FLIGHT:
            break
        time.sleep(0.1)
    assert calls == ["NVDA"] and not main._DEBATE_IN_FLIGHT
    assert client.post("/api/agent-debates/run", json={"ticker": "NVDA"}).status_code == 202


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

ANCHOR = {"price": 271.5, "prev_close": 268.0, "year_high": 290.0, "year_low": 180.0,
          "at": "2026-11-01T14:00:00+00:00"}


def _fake_framework(tmp_path, monkeypatch):
    fake = tmp_path / "fake_python.py"
    fake.write_text("import json, sys\nprint(json.dumps(" + repr(RAW) + "))\n")
    monkeypatch.setattr(runner, "framework_python", lambda: Path(sys.executable))
    monkeypatch.setattr(runner, "_RUNNER", fake)
    return lambda cmd, **kw: subprocess.run([sys.executable, str(fake)],
                                            capture_output=True, text=True)


def test_runner_attaches_the_market_anchor(agents_dir, tmp_path, monkeypatch):
    # Kevin (2026-11-03): the debate's price claims are held against the
    # market's own numbers, fetched hub-side and stored on the record.
    monkeypatch.setattr(runner, "market_anchor", lambda ticker, now=None: dict(ANCHOR))
    spawn = _fake_framework(tmp_path, monkeypatch)
    rec = runner.run_debate("PLTR", "2026-10-30", now=datetime(2026, 11, 1, tzinfo=UTC),
                            latest_session="2026-10-30", spawn=spawn)
    assert rec.status == "complete" and rec.market_anchor == ANCHOR
    card = payload.card(rec, [], latest_session="2026-10-30")
    assert card["market_anchor"]["price"] == 271.5


def test_a_fresh_debate_replaces_the_same_session_never_the_series(agents_dir, tmp_path, monkeypatch):
    old_same = _record(run_id="pltr-20261031-090000", as_of_date="2026-10-30",
                       run_at_ct="2026-10-31T09:00:00-05:00", run_at_utc="2026-10-31T14:00:00+00:00")
    old_other = _record(run_id="pltr-20261029-090000", as_of_date="2026-10-28",
                        run_at_ct="2026-10-29T09:00:00-05:00", run_at_utc="2026-10-29T14:00:00+00:00")
    store.save_run(old_same, "# old")
    store.save_run(old_other, "# older session")
    spawn = _fake_framework(tmp_path, monkeypatch)
    rec = runner.run_debate("PLTR", "2026-10-30", now=datetime(2026, 11, 1, tzinfo=UTC),
                            latest_session="2026-10-30", spawn=spawn)
    ids = {r.run_id for r in store.list_runs()}
    assert rec.run_id in ids and old_other.run_id in ids  # the graded series stays
    assert old_same.run_id not in ids                     # the duplicate is replaced


def test_delete_run_removes_artifacts_and_grades(agents_dir):
    rec = _record()
    store.save_run(rec, "# report")
    store.upsert_grade(GradeEntry(run_id=rec.run_id, horizon=5, ret_pct=1.0,
                                  outcome="hit", graded_at="2026-11-06"))
    store.delete_run(rec.run_id)
    assert store.list_runs() == [] and store.load_grades() == []
    store.delete_run("../etc")  # a hostile id is a no-op, never a path walk


def _debate_client(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    # The feed's live-price read stays off the network here.
    from tradehub.agents import anchor
    monkeypatch.setattr(anchor, "current_prices", lambda tickers, now=None: {})
    return TestClient(main.app), main


def test_failed_run_is_shown_once_then_deleted(agents_dir, monkeypatch):
    failed = RunRecord(run_id="pltr-20261101-100000", ticker="PLTR",
                       run_at_ct="2026-11-01T10:00:00-05:00",
                       run_at_utc="2026-11-01T15:00:00+00:00", as_of_date="2026-10-30",
                       status="failed_error", error="Gemini free-tier daily quota exhausted")
    store.save_run(failed, "# failed")
    client, main = _debate_client(monkeypatch)
    try:
        first = client.get("/api/agent-debates").json()
        assert [c["ticker"] for c in first["cards"]] == ["PLTR"]
        assert "quota exhausted" in first["cards"][0]["error"]
        second = client.get("/api/agent-debates").json()
        assert second["cards"] == [] and store.list_runs() == []
    finally:
        main.app.dependency_overrides.clear()


def test_rerun_inside_the_window_reuses_the_existing_debate(agents_dir, monkeypatch):
    fresh = _record()  # run_at 2026-11-01; the endpoint reads the real clock,
    store.save_run(fresh, "# debate")  # so relative freshness is what matters:
    # store a run stamped now instead
    now = datetime.now(UTC)
    recent = _record(run_id="pltr-recent", run_at_ct=now.isoformat(), run_at_utc=now.isoformat())
    store.save_run(recent, "# recent")
    client, main = _debate_client(monkeypatch)
    try:
        out = client.post("/api/agent-debates/run", json={"ticker": "PLTR"})
        assert out.status_code == 200 and out.json()["reused"] == "pltr-recent"
    finally:
        main.app.dependency_overrides.clear()

