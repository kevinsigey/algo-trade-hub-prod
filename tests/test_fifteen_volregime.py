"""The volatility-regime challenger (preregistration
docs/superpowers/specs/2026-11-13-fifteen-volregime-shadow-prereg.md): the
regime split on the frozen sigma_1m against a trailing median from earlier
days only, per-regime weights from earlier days only with the 30-window
minimum, fresh-only scoring paired against the blend, no promotion path,
the fail-soft runner hook, and the decline monitor.
"""
from datetime import UTC, date, datetime, timedelta

from tests.test_fifteen_blend import FakeSupa, _patch
from tradehub import fifteen_blend as blend
from tradehub import fifteen_volregime as vr
from tradehub import oil_fifteen_rule as rule
from tradehub.scripts import fifteen_min_run

DAY = date(2026, 11, 16)                       # Monday, after PREREG_AT
CLOSE = datetime(2026, 11, 16, 15, 30, tzinfo=UTC)  # 10:30 ET: no halt
TARGET = "kalshi:KXNATGAS15M-26NOV161030-30"
NOW = datetime(2026, 11, 16, 16, 0, tzinfo=UTC)
HIGH, LOW = 0.002, 0.0005


def _win(close: datetime, tag: str, sigma: float, prob: float, ask=0.51, bid=0.49):
    target = f"kalshi:{tag}"
    return ({"target": target, "cutoff_at": close.isoformat()},
            {"target": target, "probability": prob,
             "frozen_at": (close - timedelta(minutes=10)).isoformat(),
             "payload": {"yes_ask": ask, "yes_bid": bid, "sigma_1m": sigma}})


def _history(day: date, n: int, *, sigma: float, right: bool, tag: str):
    """n settled windows on `day`, half up half down: the model is either
    exactly right (slope > 1, clamps to 1) or exactly wrong (slope < 0)."""
    cals, fcs, settled = [], [], {}
    start = datetime(day.year, day.month, day.day, 1, 0, tzinfo=UTC)
    for i in range(n):
        up = i % 2 == 0
        cal, fc = _win(start + timedelta(minutes=15 * i), f"{tag}{i}", sigma, 0.8 if up else 0.2)
        cals.append(cal)
        fcs.append(fc)
        settled[cal["target"]] = int(up == right)
    return cals, fcs, settled


def _use(monkeypatch, world):
    calendars, forecasts, settlements = world
    _patch(monkeypatch, calendars=calendars, forecasts=forecasts, settlements=settlements)


def _world(*parts):
    cals, fcs, settled = [], [], {}
    for c, f, s in parts:
        cals += c
        fcs += f
        settled.update(s)
    return {"natgas_15m": cals}, {"natgas_15m": fcs}, settled


def _base_history():
    """Nov 15: 30 right high-vol windows, 30 wrong low-vol windows."""
    prior = DAY - timedelta(days=1)
    return (_history(prior, 30, sigma=HIGH, right=True, tag="H"),
            _history(prior, 30, sigma=LOW, right=False, tag="L"))


# -- the split and the minimum ------------------------------------------------

def test_regime_split_is_strictly_above_the_median():
    assert vr.regime_of(0.003, 0.002) == "high"
    assert vr.regime_of(0.002, 0.002) == "low"
    assert vr.regime_of(0.001, 0.002) == "low"
    assert vr.regime_of(None, 0.002) is None and vr.regime_of(0.001, None) is None


def test_under_thirty_contested_windows_gives_zero():
    right = [(0.8, 0.5, 1), (0.2, 0.5, 0)]
    weight, slope, n = vr.regime_weight(right * 14 + [(0.8, 0.5, 1)])
    assert n == 29 and slope > 1 and weight == 0.0
    weight, _slope, n = vr.regime_weight(right * 15)
    assert n == 30 and weight == 1.0
    # Uncontested rows never count toward the 30.
    weight, _slope, n = vr.regime_weight(right * 14 + [(0.99, 0.95, 1)] * 5)
    assert n == 28 and weight == 0.0


# -- no look-ahead ------------------------------------------------------------

def test_median_and_weights_use_earlier_days_only(monkeypatch):
    high, low = _base_history()
    _use(monkeypatch, _world(high, low))
    clean = vr.weights_for_day(FakeSupa(), "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY, NOW)
    assert clean[0] == (HIGH + LOW) / 2
    assert clean[1] == {"high": 1.0, "low": 0.0}

    # The day itself and the day after: 60 high-vol windows where the model
    # is exactly wrong, with sigmas far above anything earlier. Either would
    # move the median and flip the high weight if they leaked in.
    future_today = _history(DAY, 40, sigma=0.05, right=False, tag="T")
    future_next = _history(DAY + timedelta(days=1), 40, sigma=0.05, right=False, tag="N")
    # Too old for the 10-day median (but inside the weight history).
    old = _history(DAY - timedelta(days=11), 4, sigma=0.9, right=True, tag="O")
    _use(monkeypatch, _world(high, low, future_today, future_next, old))
    supa = FakeSupa()
    leaked = vr.weights_for_day(supa, "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY, NOW)
    assert leaked == clean
    rows = {r["regime"]: r for r in supa.tables[vr.WEIGHTS_TABLE]}
    assert rows["high"]["n_contested"] == 30 + 4 and rows["low"]["n_contested"] == 30
    assert rows["high"]["median_sigma"] == (HIGH + LOW) / 2


def test_no_earlier_sigma_means_no_regime_and_zero_weight(monkeypatch):
    cal, fc = _win(CLOSE, "KXNATGAS15M-26NOV161030-30", HIGH, 0.95)
    _patch(monkeypatch, calendars={"natgas_15m": [cal]}, forecasts={"natgas_15m": [fc]},
           settlements={})
    supa = FakeSupa()
    vr.record_volregime(supa, NOW)
    row = supa.tables[vr.DECISIONS_TABLE][0]
    assert row["regime"] is None and row["weight"] == 0.0
    assert row["action"] == "skip" and row["reason"] == "no_edge"


# -- the record and the paired score ------------------------------------------

def _today_world(prob=0.75):
    high, low = _base_history()
    cal, fc = _win(CLOSE, "KXNATGAS15M-26NOV161030-30", HIGH, prob)
    early, early_fc = _win(datetime(2026, 11, 13, 23, 45, tzinfo=UTC), "EARLY", LOW, prob)
    calendars, forecasts, settled = _world(high, low, ([cal, early], [fc, early_fc], {}))
    return calendars, forecasts, settled


def test_high_regime_buys_and_pre_prereg_windows_are_never_written(monkeypatch):
    calendars, forecasts, settled = _today_world()
    _patch(monkeypatch, calendars=calendars, forecasts=forecasts, settlements=settled)
    supa = FakeSupa()
    vr.record_volregime(supa, NOW, lookback=timedelta(days=4))
    rows = {r["target"]: r for r in supa.tables[vr.DECISIONS_TABLE]}
    assert "kalshi:EARLY" not in rows   # opened Nov 13 23:30 UTC, before PREREG_AT
    row = rows[TARGET]
    assert row["gate_version"] == "v3-volregime-shadow"
    assert row["regime"] == "high" and row["weight"] == 1.0 and row["sigma_1m"] == HIGH
    assert row["action"] == "buy" and row["side"] == "yes"
    # Segmentation: the live rule's and the blend's tables are untouched.
    assert rule.DECISIONS_TABLE not in supa.tables and blend.DECISIONS_TABLE not in supa.tables
    count = len(rows)
    today = [r for r in supa.tables[vr.WEIGHTS_TABLE] if r["day"] == DAY.isoformat()]
    assert {r["regime"]: r["weight"] for r in today} == {"high": 1.0, "low": 0.0}
    stamp = today[0]["computed_at"]
    vr.record_volregime(supa, NOW + timedelta(minutes=5), lookback=timedelta(days=4))
    assert len(supa.tables[vr.DECISIONS_TABLE]) == count
    again = [r for r in supa.tables[vr.WEIGHTS_TABLE] if r["day"] == DAY.isoformat()]
    assert len(again) == 2 and again[0]["computed_at"] == stamp


def _decision(table_rows, *, target, window_open, action, pnl, outcome=1, series="KXNATGAS15M"):
    table_rows.append({"series": series, "target": target, "window_open": window_open,
                       "action": action, "pnl": pnl, "outcome": outcome})


def test_paired_against_the_blend_on_the_same_windows():
    supa = FakeSupa()
    mine = supa.tables.setdefault(vr.DECISIONS_TABLE, [])
    theirs = supa.tables.setdefault(blend.DECISIONS_TABLE, [])
    fresh = "2026-11-16T15:15:00+00:00"
    _decision(mine, target="A", window_open=fresh, action="buy", pnl=0.4)
    _decision(theirs, target="A", window_open=fresh, action="skip", pnl=None)
    _decision(mine, target="B", window_open=fresh, action="buy", pnl=-0.5)
    _decision(theirs, target="B", window_open=fresh, action="buy", pnl=-0.5)
    _decision(mine, target="C", window_open=fresh, action="skip", pnl=None)   # no blend row
    _decision(mine, target="D", window_open=fresh, action="buy", pnl=0.3, outcome=None)
    _decision(theirs, target="D", window_open=fresh, action="buy", pnl=0.3)
    # Pre-prereg rows never count, on either side.
    _decision(mine, target="E", window_open="2026-11-13T15:00:00+00:00", action="buy", pnl=0.9)
    _decision(theirs, target="E", window_open="2026-11-13T15:00:00+00:00", action="skip", pnl=None)
    ev = vr._evaluate(supa)
    assert ev["trades"] == 2 and ev["net_per_contract"] == -0.05
    assert ev["paired_windows"] == 2 and ev["paired_delta"] == 0.2


def test_evaluation_records_the_bar_but_never_promotes(monkeypatch):
    supa = FakeSupa()
    monkeypatch.setattr(blend, "criterion_met", lambda *_a: True)
    ev = vr.evaluate_daily(supa, NOW)
    assert ev["criterion_met"] and not ev["blend_promoted"] and not ev["eligible"]
    assert vr.evaluate_daily(supa, NOW + timedelta(hours=1)) == {"skipped": "already_evaluated_today"}
    assert len(supa.tables[vr.EVALS_TABLE]) == 1
    # Once the blend is promoted the row says eligible -- and still writes no promotion.
    supa.tables[blend.PROMOTIONS_TABLE] = [{"id": 1, "created_at": NOW.isoformat(),
                                            "kind": "promotion", "to_version": blend.LIVE_VERSION}]
    ev = vr.evaluate_daily(supa, NOW + timedelta(days=1))
    assert ev["eligible"] and len(supa.tables[blend.PROMOTIONS_TABLE]) == 1
    assert not any("promotion" in t for t in supa.tables if t.startswith("fifteen_volregime"))
    assert vr.summary(supa)["promotion"]["path_built"] is False


# -- the runner hook ------------------------------------------------------------

def test_runner_hook_is_fail_soft(monkeypatch):
    def boom(_s, _n):
        raise RuntimeError("volregime exploded")
    monkeypatch.setattr(fifteen_min_run.fifteen_volregime, "record_volregime", boom)
    monkeypatch.setattr(fifteen_min_run.fifteen_volregime, "evaluate_daily", boom)
    ok = {"ran": True}
    for mod, fn in ((fifteen_min_run.fifteen_tracking, "record_decisions"),
                    (fifteen_min_run.fifteen_tracking, "record_offsets"),
                    (fifteen_min_run.fifteen_shadow, "record_shadow"),
                    (fifteen_min_run.fifteen_shadow, "evaluate_daily"),
                    (fifteen_min_run.fifteen_blend, "record_blend"),
                    (fifteen_min_run.fifteen_blend, "evaluate_daily")):
        monkeypatch.setattr(mod, fn, lambda *_a, **_k: ok)
    summary = fifteen_min_run.run(object(), [], NOW)
    assert "volregime exploded" in summary["fifteen_volregime"]["error"]
    assert "volregime exploded" in summary["fifteen_volregime_eval"]["error"]
    # Everything around it still ran.
    assert summary["fifteen_blend"] == ok and summary["fifteen_decisions"] == ok
    assert "fifteen_metals_offsets" in summary


# -- the decline monitor ----------------------------------------------------------

def test_decline_monitor_side_by_side_per_et_day_and_series():
    supa = FakeSupa()
    live = supa.tables.setdefault(rule.DECISIONS_TABLE, [])
    _decision(live, target="a", window_open="2026-11-16T15:00:00+00:00", action="buy", pnl=0.2)
    _decision(live, target="b", window_open="2026-11-16T15:15:00+00:00", action="buy", pnl=-0.1)
    _decision(live, target="c", window_open="2026-11-16T15:30:00+00:00", action="skip", pnl=None)
    # 03:00 UTC Nov 16 is still Nov 15 in New York.
    _decision(live, target="d", window_open="2026-11-16T03:00:00+00:00", action="buy", pnl=0.5)
    _decision(live, target="e", window_open="2026-11-16T15:00:00+00:00", action="buy", pnl=-0.3,
              series="KXCOPPER15M")
    _decision(supa.tables.setdefault(blend.DECISIONS_TABLE, []), target="a",
              window_open="2026-11-16T15:00:00+00:00", action="buy", pnl=0.2)
    rows = vr.decline_monitor(supa, NOW)
    by = {(r["day"], r["series"]): r for r in rows}
    gas = by[("2026-11-16", "Natural gas")]
    assert gas["live"] == {"trades": 2, "pnl_per_trade": 0.05}
    assert gas["blend"] == {"trades": 1, "pnl_per_trade": 0.2}
    assert gas["volregime"] == {"trades": 0, "pnl_per_trade": None}
    assert by[("2026-11-15", "Natural gas")]["live"]["trades"] == 1
    assert by[("2026-11-16", "Copper")]["live"]["pnl_per_trade"] == -0.3
    assert rows[0]["day"] == "2026-11-16"


# -- review fixes ---------------------------------------------------------------

def test_one_history_read_per_series_day_matches_the_per_regime_split(monkeypatch):
    high, low = _base_history()
    world = _world(high, low, _history(DAY - timedelta(days=2), 6, sigma=LOW, right=True, tag="X"))
    _use(monkeypatch, world)
    calls = []
    real = blend._history_triples
    monkeypatch.setattr(blend, "_history_triples", lambda *a, **k: calls.append(1) or real(*a, **k))
    median, weights = vr.weights_for_day(FakeSupa(), "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY, NOW)
    assert len(calls) == 1
    # The reference: each regime's triples built straight from the fixture.
    _cals, forecasts, settled = world
    for regime in vr.REGIMES:
        triples = [(f["probability"], 0.5, settled[f["target"]]) for f in forecasts["natgas_15m"]
                   if vr.regime_of(f["payload"]["sigma_1m"], median) == regime]
        assert weights[regime] == vr.regime_weight(triples)[0]
    assert weights == {"high": 1.0, "low": 0.0}


def test_saved_weights_are_read_back_and_a_late_settlement_never_rewrites_the_day(monkeypatch):
    high, low = _base_history()
    _use(monkeypatch, _world(high, low))
    supa = FakeSupa()
    first = vr.weights_for_day(supa, "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY, NOW)
    saved = [dict(r) for r in supa.tables[vr.WEIGHTS_TABLE]]
    # Late settlements land for earlier days: 40 high-vol windows the model got wrong.
    late = _history(DAY - timedelta(days=3), 40, sigma=HIGH, right=False, tag="LATE")
    _use(monkeypatch, _world(high, low, late))
    again = vr.weights_for_day(supa, "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY,
                               NOW + timedelta(hours=2))
    assert again == first and supa.tables[vr.WEIGHTS_TABLE] == saved
    # A fresh compute on the same evidence would have differed: the read-back is what held it.
    fresh = vr.weights_for_day(FakeSupa(), "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY, NOW)
    assert fresh != first


def test_a_failed_weights_read_raises_instead_of_computing(monkeypatch):
    high, low = _base_history()
    _use(monkeypatch, _world(high, low))

    class Broken(FakeSupa):
        def table(self, name):
            if name == vr.WEIGHTS_TABLE:
                raise RuntimeError("statement timeout")
            return super().table(name)

    supa = Broken()
    try:
        vr.weights_for_day(supa, "natgas_15m", "natgas-15m-v2", "KXNATGAS15M", DAY, NOW)
    except RuntimeError as exc:
        assert "timeout" in str(exc)
    else:
        raise AssertionError("a failed weights read must raise")
    assert vr.WEIGHTS_TABLE not in supa.tables


def test_day_clustered_low95_is_wider_when_same_day_windows_move_together():
    # Six days, 20 windows each; every window on a day has the same result.
    days = [0.5, -0.4, 0.45, -0.35, 0.5, -0.3]
    items = [(("KXNATGAS15M", f"d{i}"), x + (0.01 if j % 2 else -0.01))
             for i, x in enumerate(days) for j in range(20)]
    _n, mean, iid = blend._mean_low95([x for _k, x in items])
    clustered = vr.clustered_low95(items)
    assert clustered < iid < mean
    assert vr.clustered_low95(items[:20]) is None   # one day: not measurable


def test_clustered_figures_ride_the_evals_row_and_summary():
    supa = FakeSupa()
    mine = supa.tables.setdefault(vr.DECISIONS_TABLE, [])
    theirs = supa.tables.setdefault(blend.DECISIONS_TABLE, [])
    for d, pnl in ((16, 0.4), (17, -0.2), (18, 0.3)):
        for j in range(3):
            at = f"2026-11-{d}T15:{15 * j:02d}:00+00:00"
            _decision(mine, target=f"{d}{j}", window_open=at, action="buy", pnl=pnl)
            _decision(theirs, target=f"{d}{j}", window_open=at, action="skip", pnl=None)
    vr.evaluate_daily(supa, NOW)
    row = supa.tables[vr.EVALS_TABLE][0]
    assert row["low95_clustered"] is not None and row["low95_clustered"] < row["low95"]
    assert row["paired_low95_clustered"] is not None
    s = vr.summary(supa)
    assert s["fresh"]["clustered_low95"] == row["low95_clustered"]
    assert s["paired"]["clustered_low95"] == row["paired_low95_clustered"]


def test_decline_monitor_starts_at_new_york_midnight():
    supa = FakeSupa()
    live = supa.tables.setdefault(rule.DECISIONS_TABLE, [])
    # NOW is Nov 16 11:00 ET; 14 days back is Nov 2 00:00 ET (05:00 UTC, EST after Nov 1).
    _decision(live, target="in", window_open="2026-11-02T05:00:00+00:00", action="buy", pnl=0.1)
    _decision(live, target="in2", window_open="2026-11-02T20:00:00+00:00", action="buy", pnl=0.3)
    _decision(live, target="out", window_open="2026-11-02T04:45:00+00:00", action="buy", pnl=0.9)
    by = {r["day"]: r for r in vr.decline_monitor(supa, NOW)}
    assert "2026-11-01" not in by
    assert by["2026-11-02"]["live"] == {"trades": 2, "pnl_per_trade": 0.2}
