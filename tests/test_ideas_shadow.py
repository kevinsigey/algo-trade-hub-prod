from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from workshop_fake import DB

from tradehub.scripts import ideas_shadow
from tradehub.workshop import store

SPEC = {"title": "AAA beats SPY", "hold": ["AAA"], "claim": "beats_benchmark", "start": "2024-01-02"}
IDX = pd.bdate_range("2024-01-02", "2026-11-13")


def prices(gap: str | None = None):
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(IDX))) for t in
                          ("AAA", "SPY", "QQQ", "IWM")}, index=IDX)
    if gap:
        frame.loc[pd.Timestamp(gap), "AAA"] = np.nan
    return frame


def fake_closes(frame):
    def closes(tickers, start):
        return frame[[t for t in tickers if t in frame]]
    return closes


@pytest.fixture
def db():
    d = DB()
    store.create_idea(d, "AAA beats SPY", "words")
    d.table("idea_runs").insert({"idea_id": 1, "variation": 1, "spec": SPEC, "verdict": "PASS",
                                 "result": {}, "data_end": "2026-10-29"}).execute()
    d.db["ideas"][0].update({"live_at": "2026-11-02T15:00:00+00:00", "live_run_id": 1, "size_pct": 10})
    return d


def _run(*a, **k):
    added, failed = ideas_shadow.run(*a, **k)
    assert failed == {}
    return added


def evening(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T23:00:00+00:00").astimezone(UTC)


def test_first_run_starts_the_day_after_go_live(db):
    out = _run(evening("2026-11-04"), db, closes=fake_closes(prices()), fred=None)
    assert out == {1: 2}
    assert [r["day"] for r in store.shadow_days(db, 1)] == ["2026-11-03", "2026-11-04"]


def test_gap_is_filled_in_order_and_rerun_adds_nothing(db):
    closes = fake_closes(prices())
    _run(evening("2026-11-03"), db, closes=closes, fred=None)
    assert _run(evening("2026-11-10"), db, closes=closes, fred=None) == {1: 5}
    assert [r["day"] for r in store.shadow_days(db, 1)][-1] == "2026-11-10"
    assert _run(evening("2026-11-10"), db, closes=closes, fred=None) == {1: 0}


def test_no_close_means_no_row(db):
    _run(evening("2026-11-06"), db, closes=fake_closes(prices(gap="2026-11-04")), fred=None)
    assert "2026-11-04" not in [r["day"] for r in store.shadow_days(db, 1)]


def test_killed_idea_gets_nothing(db):
    db.db["ideas"][0]["killed_at"] = "2026-11-03T15:00:00+00:00"
    assert _run(evening("2026-11-06"), db, closes=fake_closes(prices()), fred=None) == {}


def test_today_counts_only_after_the_close(db):
    midday = datetime.fromisoformat("2026-11-04T16:00:00+00:00")
    _run(midday, db, closes=fake_closes(prices()), fred=None)
    assert [r["day"] for r in store.shadow_days(db, 1)] == ["2026-11-03"]


def test_shadow_days_equal_the_backtest_rule_with_a_long_lookback(db):
    # Review finding 2: a 756-trading-day condition must be warm on the first shadow day, exactly as in the backtest.
    from tradehub.workshop.engine import daily_frame
    from tradehub.workshop.spec import IdeaSpec
    idx = pd.bdate_range("2018-01-02", "2026-11-13")
    idx = idx[(np.arange(len(idx)) % 25 != 7) | (idx >= "2026-11-02")]  # ~10 market holidays a year
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(idx))) for t in
                          ("AAA", "SPY", "QQQ", "IWM")}, index=idx)
    spec = {**SPEC, "start": "2018-01-02", "otherwise": "SPY",
            "when": {"source": "price", "series": "AAA", "measure": "pct_change", "lookback_days": 756, "op": ">",
                     "threshold": 0.0}}
    db.db["idea_runs"][0]["spec"] = spec
    _run(evening("2026-11-13"), db, closes=fake_closes(frame), fred=None)
    want = daily_frame(IdeaSpec.model_validate(spec), frame, {})
    got = store.shadow_days(db, 1)
    assert len(got) == 9
    for row in got:
        ref = want.loc[pd.Timestamp(row["day"])]
        assert row["on"] == bool(ref["on"]) and row["ret"] == pytest.approx(float(ref["ret"]))


def test_one_broken_idea_does_not_stop_the_others(db):
    # Review finding 3: a delisted ticker in one idea must not leave every other idea without rows.
    store.create_idea(db, "Broken", "words")
    db.table("idea_runs").insert({"idea_id": 2, "variation": 1, "spec": {**SPEC, "hold": ["GONE"]}, "verdict": "PASS",
                                  "result": {}, "data_end": "2026-10-29"}).execute()
    db.db["ideas"][1].update({"live_at": "2026-11-02T15:00:00+00:00", "live_run_id": 2, "size_pct": 10})
    added, failed = ideas_shadow.run(evening("2026-11-04"), db, closes=fake_closes(prices()), fred=None)
    assert added == {1: 2} and list(failed) == [2] and "GONE" in failed[2]


def test_catch_up_records_the_same_exit_day_as_the_backtest(db):
    # Step 5 review focus 3: a stop inside a 5-day catch-up lands on the backtest's day, with entry kept.
    from tradehub.workshop.engine import daily_frame
    from tradehub.workshop.spec import IdeaSpec
    frame = prices()
    frame.loc[pd.Timestamp("2026-11-05"), "AAA"] = frame.loc[pd.Timestamp("2026-11-04"), "AAA"] * 0.9
    frame.loc[pd.Timestamp("2026-11-06"):, "AAA"] = frame.loc[pd.Timestamp("2026-11-05"), "AAA"]
    spec = {**SPEC, "exits": {"stop_loss_pct": 5}}
    db.db["idea_runs"][0]["spec"] = spec
    _run(evening("2026-11-10"), db, closes=fake_closes(frame), fred=None)
    got = {r["day"]: (r["exit"], r["ret"]) for r in store.shadow_days(db, 1)}
    want = daily_frame(IdeaSpec.model_validate(spec), frame, {})
    assert (want["exit"] != "").sum() > 3  # the path really has exits in it
    assert len(got) == 6
    for day, (why, ret) in got.items():
        assert why == want.loc[pd.Timestamp(day), "exit"] and ret == pytest.approx(want.loc[pd.Timestamp(day), "ret"])


def test_intraday_ideas_read_daily_bars(db):
    db.db["idea_runs"][0]["spec"] = {**SPEC, "exits": {"stop_loss_pct": 5, "mode": "intraday"}}
    seen = []

    def bars(tickers, start):
        seen.append(tuple(tickers))
        f = prices()
        return {t: pd.DataFrame({"open": f[t], "high": f[t], "low": f[t], "close": f[t]}) for t in tickers}
    added, failed = ideas_shadow.run(evening("2026-11-04"), db, closes=fake_closes(prices()), fred=None, bars=bars)
    assert failed == {} and added == {1: 2} and seen == [("AAA",)]


def test_analyst_rule_calls_analyst(db):
    spec = {"title": "AAA upgrades", "hold": ["AAA"], "claim": "beats_benchmark", "start": "2024-01-02",
            "rules": {"enter": {"conditions": [{"source": "analyst", "series": "AAA", "measure": "net_upgrades",
                                               "lookback_days": 5, "op": ">", "threshold": 0}]}}}
    db.db["idea_runs"][0]["spec"] = spec
    seen = []

    def fake_analyst(ticker):
        seen.append(ticker)
        return pd.DataFrame({"action": ["up"], "target": [float("nan")]},
                            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02")]))
    _run(evening("2026-11-04"), db, closes=fake_closes(prices()), fred=None, analyst=fake_analyst)
    assert seen == ["AAA"]