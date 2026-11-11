"""The self-weighting blend shadow (preregistration
docs/superpowers/specs/2026-11-11-fifteen-blend-shadow-prereg.md): the daily
earned weight from previous days only, contested windows only, clamped to
[0, 1]; the blend gate on the live rule's own evaluate; fresh windows only;
the three-legged promotion criterion on the blend's own log; one-action
reversal; hard segmentation from the live record and the oil shadow.
"""
from datetime import UTC, datetime, timedelta

from tradehub import fifteen_blend as blend
from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule

# Thursday Nov 12, 2026, 15:30Z close = 10:30 ET: futures open, no halt.
CLOSE = datetime(2026, 11, 12, 15, 30, tzinfo=UTC)
TARGET = "kalshi:KXNATGAS15M-26NOV121030-30"
FROZEN = "2026-11-12T15:20:00+00:00"
NOW = datetime(2026, 11, 12, 16, 0, tzinfo=UTC)


class FakeSupa:
    """A tiny in-memory PostgREST: select with eq/gte/in_ filters, order,
    range; upsert on conflict keys; insert with an identity id."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self._ids: dict[str, int] = {}

    def table(self, name):
        supa = self

        class _Q:
            def __init__(self):
                self.filters = []
                self.mode = "select"
                self.payload = None
                self.conflict = None
                self.span = None

            def select(self, *_a):
                self.mode = "select"
                return self

            def eq(self, col, val):
                self.filters.append(lambda r: r.get(col) == val)
                return self

            def gte(self, col, val):
                self.filters.append(lambda r: r.get(col) is not None and r[col] >= val)
                return self

            def in_(self, col, vals):
                keep = set(vals)
                self.filters.append(lambda r: r.get(col) in keep)
                return self

            def order(self, *_a):
                return self

            def range(self, lo, hi):
                self.span = (lo, hi)
                return self

            def upsert(self, rows, on_conflict=None):
                self.mode, self.payload, self.conflict = "upsert", rows, on_conflict
                return self

            def insert(self, row):
                self.mode, self.payload = "insert", row
                return self

            def execute(self):
                tbl = supa.tables.setdefault(name, [])
                if self.mode == "upsert":
                    keys = self.conflict.split(",")
                    for r in self.payload:
                        r = dict(r)
                        for i, old in enumerate(tbl):
                            if all(old.get(k) == r.get(k) for k in keys):
                                tbl[i] = r
                                break
                        else:
                            supa._ids[name] = supa._ids.get(name, 0) + 1
                            r.setdefault("id", supa._ids[name])
                            tbl.append(r)
                    return type("R", (), {"data": []})()
                if self.mode == "insert":
                    supa._ids[name] = supa._ids.get(name, 0) + 1
                    row = dict(self.payload)
                    row.setdefault("id", supa._ids[name])
                    tbl.append(row)
                    return type("R", (), {"data": [row]})()
                rows = [dict(r) for r in tbl if all(f(r) for f in self.filters)]
                if self.span:
                    rows = rows[self.span[0]:self.span[1] + 1]
                return type("R", (), {"data": rows})()

        return _Q()


def _patch(monkeypatch, *, calendars, forecasts, settlements):
    """calendars: {family: [{target, cutoff_at}]}; forecasts: {family: [rows]};
    the fakes honour the real functions' contracts (window + target filter)."""

    def fetch_targets(supa, family, since, until):
        return [t for t in calendars.get(family, [])
                if since <= datetime.fromisoformat(t["cutoff_at"]) <= until]

    monkeypatch.setattr(tracking, "fetch_targets", fetch_targets)
    monkeypatch.setattr(blend.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None:
                        [r for r in forecasts.get(f, [])
                         if targets is None or r["target"] in targets])
    monkeypatch.setattr(blend.store, "fetch_settlements",
                        lambda supa, names: {t: settlements[t] for t in names
                                             if t in settlements})


def _hist(day="2026-11-11", prob=0.80, outcome=1, ask=0.51, bid=0.49, tag="H1"):
    close = f"{day}T15:30:00+00:00"
    return ({"target": f"kalshi:{tag}", "cutoff_at": close},
            {"target": f"kalshi:{tag}", "probability": prob,
             "frozen_at": f"{day}T15:20:00+00:00",
             "payload": {"yes_ask": ask, "yes_bid": bid}})


def _perfect_history():
    """Two Nov 11 windows the model called exactly: slope > 1, clamps to 1."""
    c1, f1 = _hist(prob=0.80, outcome=1, tag="H1")
    c2, f2 = _hist(prob=0.20, outcome=0, tag="H2")
    return {"natgas_15m": [c1, c2]}, {"natgas_15m": [f1, f2]}, \
        {"kalshi:H1": 1, "kalshi:H2": 0}


def _today(prob=0.75, ask=0.51, bid=0.49):
    cal = {"target": TARGET, "cutoff_at": CLOSE.isoformat()}
    fc = {"target": TARGET, "probability": prob, "frozen_at": FROZEN,
          "payload": {"yes_ask": ask, "yes_bid": bid}}
    return cal, fc


# -- the earned weight -------------------------------------------------------

def test_earned_weight_slope_and_contested_filter():
    # A model that is the market has nothing to regress on: the row is
    # contested and counted, but the slope is undefined.
    assert blend.earned_weight([(0.5, 0.5, 1)]) == (None, 1)
    assert blend.earned_weight([]) == (None, 0)
    # Perfect calls at a 0.5 market: slope 0.5/0.3 > 1 raw.
    slope, n = blend.earned_weight([(0.8, 0.5, 1), (0.2, 0.5, 0)])
    assert n == 2 and slope > 1.0
    # Exactly wrong: negative slope.
    slope, _ = blend.earned_weight([(0.8, 0.5, 0), (0.2, 0.5, 1)])
    assert slope < 0
    # A 0.95 market is not contested: the row never counts.
    slope, n = blend.earned_weight([(0.99, 0.95, 1), (0.8, 0.5, 1), (0.2, 0.5, 0)])
    assert n == 2 and slope > 1.0


# -- the record ---------------------------------------------------------------

def test_blend_buys_at_full_weight_and_stamps_the_day_weight(monkeypatch):
    calendars, forecasts, settlements = _perfect_history()
    cal, fc = _today()
    calendars["natgas_15m"].append(cal)
    forecasts["natgas_15m"].append(fc)
    _patch(monkeypatch, calendars=calendars, forecasts=forecasts,
           settlements=settlements)
    supa = FakeSupa()
    out = blend.record_blend(supa, NOW)
    rows = supa.tables[blend.DECISIONS_TABLE]
    assert out["windows"] == 1 and len(rows) == 1
    row = rows[0]
    assert row["gate_version"] == "v2-blend-shadow" and row["action"] == "buy"
    assert row["weight"] == 1.0 and row["blend_prob"] == 0.75
    assert row["market_prob"] == 0.5 and row["model_prob"] == 0.75
    # The day's weight was persisted once, with its evidence.
    weights = supa.tables[blend.WEIGHTS_TABLE]
    assert len(weights) == 1 and weights[0]["day"] == "2026-11-12"
    assert weights[0]["n_contested"] == 2 and weights[0]["weight"] == 1.0
    # Segmentation: nothing lands in the live decisions table.
    assert rule.DECISIONS_TABLE not in supa.tables
    # A second pass upserts the same row and reuses the persisted weight.
    stamp = weights[0]["computed_at"]
    blend.record_blend(supa, NOW + timedelta(minutes=5))
    assert len(supa.tables[blend.DECISIONS_TABLE]) == 1
    assert supa.tables[blend.WEIGHTS_TABLE][0]["computed_at"] == stamp


def test_no_history_means_zero_weight_and_no_trade(monkeypatch):
    cal, fc = _today(prob=0.95)
    _patch(monkeypatch, calendars={"natgas_15m": [cal]},
           forecasts={"natgas_15m": [fc]}, settlements={})
    supa = FakeSupa()
    blend.record_blend(supa, NOW)
    row = supa.tables[blend.DECISIONS_TABLE][0]
    assert row["weight"] == 0.0 and row["blend_prob"] == 0.5
    assert row["action"] == "skip" and row["reason"] == "no_edge"


def test_windows_before_the_preregistration_are_never_written(monkeypatch):
    cal, fc = _today()
    cal = {**cal, "cutoff_at": "2026-11-11T23:45:00+00:00",
           "target": "kalshi:EARLY"}
    fc = {**fc, "target": "kalshi:EARLY", "frozen_at": "2026-11-11T23:35:00+00:00"}
    _patch(monkeypatch, calendars={"natgas_15m": [cal]},
           forecasts={"natgas_15m": [fc]}, settlements={})
    supa = FakeSupa()
    out = blend.record_blend(supa, datetime(2026, 11, 12, 1, 0, tzinfo=UTC))
    assert out["windows"] == 0
    assert blend.DECISIONS_TABLE not in supa.tables


def test_missing_forecast_and_missing_quotes_are_named(monkeypatch):
    cal, _fc = _today()
    bare = {"target": "kalshi:BARE", "cutoff_at": "2026-11-12T15:45:00+00:00"}
    _patch(monkeypatch, calendars={"natgas_15m": [cal, bare]},
           forecasts={"natgas_15m": [
               {"target": TARGET, "probability": 0.9, "frozen_at": FROZEN,
                "payload": {"yes_ask": None, "yes_bid": None}}]},
           settlements={})
    supa = FakeSupa()
    blend.record_blend(supa, NOW)
    rows = {r["target"]: r for r in supa.tables[blend.DECISIONS_TABLE]}
    assert rows[TARGET]["reason"] == "no_quote" and rows[TARGET]["blend_prob"] is None
    assert rows["kalshi:BARE"]["reason"] == "no_prediction"


def test_halt_parity_with_the_live_rule(monkeypatch):
    cal = {"target": "kalshi:HALT", "cutoff_at": "2026-11-12T22:00:00+00:00"}
    fc = {"target": "kalshi:HALT", "probability": 0.95,
          "frozen_at": "2026-11-12T21:50:00+00:00",  # 16:50 ET, inside the halt
          "payload": {"yes_ask": 0.51, "yes_bid": 0.49}}
    _patch(monkeypatch, calendars={"natgas_15m": [cal]},
           forecasts={"natgas_15m": [fc]}, settlements={})
    supa = FakeSupa()
    blend.record_blend(supa, datetime(2026, 11, 12, 23, 0, tzinfo=UTC))
    row = supa.tables[blend.DECISIONS_TABLE][0]
    assert row["action"] == "skip" and row["reason"] == "halt"


# -- promotion -----------------------------------------------------------------

def test_criterion_needs_all_three_legs():
    assert blend.criterion_met(100, 0.01, 0.01)
    assert not blend.criterion_met(99, 0.01, 0.01)
    assert not blend.criterion_met(100, 0.0, 0.01)
    assert not blend.criterion_met(100, 0.01, None)
    assert not blend.criterion_met(100, None, 0.01)


def _seed_promotable(supa, n=110):
    """n fresh settled blend wins, each paired against a live skip."""
    blend_rows, live_rows = [], []
    for i in range(n):
        target = f"kalshi:B{i}"
        blend_rows.append({"series": "KXNATGAS15M", "target": target,
                           "window_open": "2026-11-12T01:00:00+00:00",
                           "gate_version": "v2-blend-shadow", "action": "buy",
                           "pnl": 0.40, "outcome": 1})
        live_rows.append({"series": "KXNATGAS15M", "target": target,
                          "gate_version": "v1", "action": "skip",
                          "pnl": None, "outcome": 1})
    supa.tables[blend.DECISIONS_TABLE] = blend_rows
    supa.tables[rule.DECISIONS_TABLE] = live_rows


def test_promotion_flips_state_and_revert_restores_it():
    supa = FakeSupa()
    _seed_promotable(supa)
    out = blend.evaluate_promotion(supa, NOW)
    assert out["promoted"] and out["trades"] == 110 and out["criterion_met"]
    assert blend.current_state(supa) == "v2-blend"
    assert blend.promoted_at(supa) == NOW.isoformat()
    # A second evaluation never double-promotes.
    assert not blend.evaluate_promotion(supa, NOW)["promoted"]
    back = blend.revert_promotion(supa, NOW, reason="check")
    assert back["reverted"] and blend.current_state(supa) == "v1"


def test_daily_evaluation_runs_once_a_day():
    supa = FakeSupa()
    _seed_promotable(supa, n=3)  # below the bar: an honest no-promotion trail row
    first = blend.evaluate_daily(supa, NOW)
    assert "skipped" not in first and first["promoted"] is False
    assert blend.evaluate_daily(supa, NOW + timedelta(hours=2)) == \
        {"skipped": "already_evaluated_today"}
    assert len(supa.tables[blend.EVALS_TABLE]) == 1


def test_promoted_blend_stamps_live_decisions_until_reverted(monkeypatch):
    calendars, forecasts, settlements = _perfect_history()
    cal, fc = _today()
    calendars["natgas_15m"].append(cal)
    forecasts["natgas_15m"].append(fc)
    _patch(monkeypatch, calendars=calendars, forecasts=forecasts,
           settlements=settlements)
    supa = FakeSupa()
    # The blend has flipped: a promotion row predates today's windows, and
    # today's weight is already persisted at 1.0.
    supa.tables[blend.PROMOTIONS_TABLE] = [
        {"id": 1, "created_at": "2026-11-12T00:00:00+00:00", "kind": "promotion",
         "from_version": "v1", "to_version": "v2-blend", "evidence": {}}]
    supa.tables[blend.WEIGHTS_TABLE] = [
        {"series": "KXNATGAS15M", "day": "2026-11-12", "weight": 1.0,
         "raw_slope": 1.4, "n_contested": 12, "computed_at": NOW.isoformat()}]
    tracking.record_decisions(supa, NOW)
    rows = {r["target"]: r for r in supa.tables[rule.DECISIONS_TABLE]}
    # Today's window opened after the flip: a blend decision. The Nov 11
    # history windows opened before it and stay plain v1 decisions.
    assert rows[TARGET]["gate_version"] == "v2-blend" and rows[TARGET]["action"] == "buy"
    assert rows["kalshi:H1"]["gate_version"] == "v1"
    assert rows["kalshi:H2"]["gate_version"] == "v1"
    # After a reversal the same window is a plain v1 decision again.
    blend.revert_promotion(supa, NOW, reason="test")
    supa.tables[rule.DECISIONS_TABLE] = []
    tracking.record_decisions(supa, NOW)
    rows = {r["target"]: r for r in supa.tables[rule.DECISIONS_TABLE]}
    assert rows[TARGET]["gate_version"] == "v1"


def test_summary_reports_weights_and_the_frozen_criterion():
    supa = FakeSupa()
    _seed_promotable(supa, n=5)
    supa.tables[blend.WEIGHTS_TABLE] = [
        {"series": "KXNATGAS15M", "day": "2026-11-12", "weight": 0.42,
         "raw_slope": 0.42, "n_contested": 37, "computed_at": NOW.isoformat()}]
    out = blend.summary(supa)
    assert out["gate_version"] == "v2-blend-shadow"
    assert out["promotion"]["criterion"]["min_trades"] == 100
    assert out["promotion"]["state"] == "v1" and out["fresh"]["trades"] == 5
    assert out["weights"]["KXNATGAS15M"]["weight"] == 0.42
