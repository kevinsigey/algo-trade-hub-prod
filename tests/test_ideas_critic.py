"""Loop piece 1: the weekly critic. The properties that matter: the live number is the
claim's OWN statistic recomputed on the live shadow record (like-for-like units, never
an invented metric); the recommendation is a deterministic function of days + the
live/backtest values, stated in reasons; losing entries cluster by the regime at
entry; one bad idea never stops the others; and the summary aggregates (counts +
worst degraders first), never a wall of per-idea text.
"""
from datetime import datetime, timezone

import pytest
from workshop_fake import DB

from tradehub.workshop import critic, store


def _rows(n, ret=0.001, bench=0.0, spy=0.0, on=True, start_day=1):
    return [{"day": f"2026-10-{start_day + i:02d}", "ret": ret, "bench": bench,
             "spy": spy, "on": on, "exit": ""} for i in range(n)]


# ── the live claim value is the claim's own statistic ───────────────────────────

def test_live_claim_recomputes_the_claim_statistic_on_live_rows():
    rows = _rows(20, ret=0.002, bench=0.001)
    holds, value, label = critic.live_claim("beats_benchmark", rows)
    assert holds is True and value > 0 and "pts/yr" in label


def test_live_claim_ballast_without_down_days_is_nan_not_a_guess():
    rows = _rows(20, ret=0.001, spy=0.001)  # SPY never down: ballast untestable
    holds, value, _ = critic.live_claim("ballast", rows)
    assert value != value  # NaN: stated as untestable by the caller, never a zero


# ── the recommendation is blunt and deterministic ───────────────────────────────

def test_too_little_record_is_a_watch_never_a_verdict():
    rec, reasons = critic.recommend(days=3, live_value=-50.0, backtest_value=10.0)
    assert rec == "WATCH" and "too little record" in reasons[0]


def test_a_sign_flip_against_a_positive_claim_is_a_pause():
    rec, _ = critic.recommend(days=60, live_value=-2.0, backtest_value=10.0)
    assert rec == "PAUSE"


def test_degradation_bands():
    assert critic.recommend(days=60, live_value=4.0, backtest_value=10.0)[0] == "PAUSE"   # ratio .4
    assert critic.recommend(days=60, live_value=6.0, backtest_value=10.0)[0] == "WATCH"   # ratio .6
    assert critic.recommend(days=60, live_value=9.0, backtest_value=10.0)[0] == "HOLD"    # ratio .9


def test_an_untestable_live_claim_is_a_watch_with_the_reason():
    rec, reasons = critic.recommend(days=60, live_value=float("nan"), backtest_value=10.0)
    assert rec == "WATCH" and "not been testable" in reasons[0]


def test_a_young_record_caps_a_pause_at_a_watch():
    """Annualizing a few weeks explodes the number: direction earns a watch,
    but a PAUSE needs JUDGE_DAYS of live record behind it."""
    rec, reasons = critic.recommend(days=30, live_value=-2.0, backtest_value=10.0)
    assert rec == "WATCH" and "too early" in reasons[0]
    assert critic.recommend(days=90, live_value=-2.0, backtest_value=10.0)[0] == "PAUSE"


def test_a_payload_with_a_nan_live_value_is_json_safe():
    import json

    rows = _rows(20, ret=0.001, spy=0.001)  # ballast: no down days, live value NaN
    payload = critic.critique_payload(
        idea_id=1, book="main", at="2026-11-09T23:00:00+00:00", kind="ballast",
        backtest={"value": 1.5, "label": "x", "holds": True, "verdict": "PASS",
                  "p": 0.01, "walk_forward": None},
        rows=rows, regimes={}, paper=None, prior_dominant=None)
    json.dumps(payload)  # must not raise: NaN is not JSON
    assert payload["live"]["value"] is None


# ── losing entries cluster by the regime at entry ───────────────────────────────

def test_losing_entries_cluster_by_regime_at_entry():
    # Three losing entries, all started in a downtrend/high-vol day; one winner between.
    rows = (_rows(2, ret=-0.01, bench=0.0, start_day=1)
            + _rows(1, ret=0.01, bench=0.0, on=False, start_day=3)
            + _rows(2, ret=-0.01, bench=0.0, start_day=4)
            + _rows(1, ret=0.01, bench=0.0, on=False, start_day=6)
            + _rows(2, ret=-0.02, bench=0.0, start_day=7))
    regimes = {r["day"]: {"trend": "down", "vol": "high", "label": "downtrend · high vol"}
               for r in rows}
    payload = critic.critique_payload(
        idea_id=1, book="main", at="2026-11-09T23:00:00+00:00", kind="beats_benchmark",
        backtest={"value": 10.0, "label": "+10.0 pts/yr", "holds": True,
                  "verdict": "PASS", "p": 0.01, "walk_forward": {"held": 3, "of": 4}},
        rows=rows, regimes=regimes, paper=None, prior_dominant=None)
    assert payload["conditions"]["dominant"] == "downtrend · high vol"
    assert payload["conditions"]["losing_entries"] == 3
    assert any("cluster" in f for f in payload["flags"])


def test_a_repeated_dominant_condition_is_flagged_as_repeated():
    rows = (_rows(15, ret=-0.002, bench=0.0, start_day=1)
            + _rows(1, ret=0.0, bench=0.0, on=False, start_day=16)
            + _rows(14, ret=-0.002, bench=0.0, start_day=17))
    regimes = {r["day"]: {"trend": "down", "vol": "high", "label": "downtrend · high vol"}
               for r in rows}
    payload = critic.critique_payload(
        idea_id=1, book="main", at="2026-11-09T23:00:00+00:00", kind="beats_benchmark",
        backtest={"value": 10.0, "label": "+10.0 pts/yr", "holds": True,
                  "verdict": "PASS", "p": 0.01, "walk_forward": None},
        rows=rows, regimes=regimes, paper=None,
        prior_dominant="downtrend · high vol")
    assert any("repeated" in f for f in payload["flags"])


# ── the store roundtrip ──────────────────────────────────────────────────────────

def test_latest_critiques_picks_the_newest_per_idea_and_book():
    db = DB()
    store.add_critique(db, 1, "main", {"recommendation": "HOLD", "at": "2026-11-02T23:00:00+00:00"})
    store.add_critique(db, 1, "main", {"recommendation": "PAUSE", "at": "2026-11-09T23:00:00+00:00"})
    store.add_critique(db, 1, "big", {"recommendation": "WATCH", "at": "2026-11-09T23:00:00+00:00"})
    latest = store.latest_critiques(db)
    assert latest[(1, "main")]["payload"]["recommendation"] == "PAUSE"
    assert latest[(1, "big")]["payload"]["recommendation"] == "WATCH"


# ── the weekly run writes every unit and aggregates ─────────────────────────────

SPEC = {"claim": "beats_benchmark", "start": "2020-01-02", "rules": None,
        "hold": [], "short": [], "benchmark": "SPY"}
RESULT = {"verdict": "PASS", "headline": "ok",
          "claim": {"built": {"holds": True, "value": 12.0, "label": "+12.0 pts/yr vs benchmark"},
                    "unseen": {"holds": True, "value": 10.0, "label": "+10.0 pts/yr vs benchmark"}},
          "shuffle": {"p": 0.01}, "walk_forward": {"held": 3, "of": 4}}


@pytest.fixture
def seeded():
    db = DB()
    live = store.create_idea(db, "Live one", "x")
    run = store.insert_run(db, live["id"], 0, SPEC, None, RESULT)
    store.publish(db, live["id"])
    store.go_live(db, live["id"], run["id"], 5.0, {"status": "ready"})
    tracked = store.create_idea(db, "Tracked one", "x")
    trun = store.insert_run(db, tracked["id"], 0, SPEC, None, RESULT)
    store.publish(db, tracked["id"])
    store.track(db, tracked["id"], trun["id"])
    for i in range(15):
        store.append_shadow(db, live["id"], [{"day": f"2026-10-{i + 1:02d}", "ret": -0.002,
                                              "bench": 0.0, "spy": 0.0, "on": True, "exit": ""}])
        store.append_shadow(db, tracked["id"], [{"day": f"2026-10-{i + 1:02d}", "ret": 0.002,
                                                 "bench": 0.0, "spy": 0.0, "on": True, "exit": ""}])
    return db


def _fake_closes(tickers, start, **kw):
    import pandas as pd
    idx = pd.date_range("2026-06-01", periods=140, freq="B")
    return pd.DataFrame({t: pd.Series([100.0 + i * 0.1 for i in range(140)], index=idx)
                         for t in tickers})


def test_the_weekly_run_critiques_live_and_tracked_and_aggregates(seeded):
    from tradehub.scripts import ideas_critic

    summary, failed = ideas_critic.run(datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc),
                                       seeded, closes=_fake_closes)
    assert failed == {}
    # 15 live days: the failing idea is PAUSE-band but too young to pause on.
    assert summary["counts"] == {"PAUSE": 0, "WATCH": 1, "HOLD": 1}
    assert summary["worst"][0]["recommendation"] == "WATCH"
    latest = store.latest_critiques(seeded)
    assert len(latest) == 2
    watch = [p for p in (r["payload"] for r in latest.values())
             if p["recommendation"] == "WATCH"][0]
    assert watch["degradation"] < 0 and watch["live"]["days"] == 15


# ── the API surface: aggregate summary + the critic block on the idea ──────────

@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    from tradehub.api.dependencies import get_supabase

    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def _critique(idea_id, book, rec, degradation, at="2026-11-09T23:00:00+00:00"):
    return {"idea_id": idea_id, "book": book, "at": at, "recommendation": rec,
            "degradation": degradation, "live": {"days": 40, "value": 1.0},
            "claim": {"kind": "beats_benchmark"}, "conditions": {}, "flags": [],
            "reasons": [], "paper": None}


def test_critic_summary_aggregates_counts_and_worst_first(api):
    c, db = api
    idea = store.create_idea(db, "Alpha", "x")
    store.publish(db, idea["id"])
    store.add_critique(db, idea["id"], "main", _critique(idea["id"], "main", "PAUSE", -12.5))
    store.add_critique(db, idea["id"], "big", _critique(idea["id"], "big", "HOLD", 3.0))
    other = store.create_idea(db, "Beta", "x")
    store.add_critique(db, other["id"], "main", _critique(other["id"], "main", "WATCH", -4.0))

    body = c.get("/api/ideas/critic-summary").json()
    assert body["counts"] == {"PAUSE": 1, "WATCH": 1, "HOLD": 1}
    assert body["units"] == 3
    assert [w["degradation"] for w in body["worst"]] == [-12.5, -4.0, 3.0]
    assert body["worst"][0]["title"] == "Alpha"


def test_the_worst_list_needs_a_real_record_behind_the_number(api):
    """A 3-day-old idea's -999 degradation is two days annualized, not a
    verdict: it counts in the totals but never ranks as a worst degrader."""
    c, db = api
    young = store.create_idea(db, "Young", "x")
    crit = _critique(young["id"], "main", "WATCH", -999.0)
    crit["live"]["days"] = 3
    store.add_critique(db, young["id"], "main", crit)
    body = c.get("/api/ideas/critic-summary").json()
    assert body["counts"]["WATCH"] == 1
    assert body["worst"] == []


def test_the_idea_record_carries_its_critic_block(api):
    c, db = api
    idea = store.create_idea(db, "Alpha", "x")
    store.publish(db, idea["id"])
    store.add_critique(db, idea["id"], "main", _critique(idea["id"], "main", "PAUSE", -12.5))
    row = [r for r in c.get("/api/ideas").json() if r["id"] == idea["id"]][0]
    assert row["critic"]["main"]["recommendation"] == "PAUSE"
    assert row["critic"]["main"]["degradation"] == -12.5


def test_a_big_book_activation_is_a_unit_of_its_own(seeded):
    """Regression (found live, 2026-11-03): store.get_idea returns
    {idea, runs}, not the idea row -- the big-book unit must unwrap it."""
    from tradehub.scripts import ideas_critic

    live_id = [i for i in store.live_ideas(seeded)][0]["id"]
    runs = seeded.table("idea_runs").select("*").eq("idea_id", live_id).execute().data
    store.go_live_book(seeded, "big", live_id, runs[0]["id"], 8.0, {"status": "ready"})

    summary, failed = ideas_critic.run(datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc),
                                       seeded, closes=_fake_closes)
    assert failed == {}
    assert summary["units"] == 3  # main live + main tracked + big activation
    assert (live_id, "big") in store.latest_critiques(seeded)


def test_one_broken_idea_never_stops_the_others(seeded, monkeypatch):
    from tradehub.scripts import ideas_critic

    real = store.get_run

    def flaky(supa, run_id):
        if run_id == 2:
            raise RuntimeError("boom")
        return real(supa, run_id)

    monkeypatch.setattr(ideas_critic.store, "get_run", flaky)
    summary, failed = ideas_critic.run(datetime(2026, 11, 9, 23, 0, tzinfo=timezone.utc),
                                       seeded, closes=_fake_closes)
    assert len(failed) == 1 and summary["counts"]["WATCH"] == 1
