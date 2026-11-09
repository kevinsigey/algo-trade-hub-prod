"""The oil minute-1 x 0.05-bar shadow variant (preregistration
docs/superpowers/specs/2026-11-09-fifteen-shadow-oil-minute1-prereg.md):
its own tagged decision rows over the offsets 1..5 x bars {0.05, 0.10} grid,
fresh windows only, tape never counts, halt parity with the live rule, the
three-legged promotion criterion, one-action reversal, and hard segmentation
from the v1 record.
"""
from datetime import UTC, datetime, timedelta

from tradehub import fifteen_shadow as shadow
from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule

OPEN = datetime(2026, 11, 13, 21, 15, tzinfo=UTC)   # Friday 16:15 ET, futures open
CLOSE = OPEN + timedelta(minutes=15)
TARGET = "kalshi:KXWTI15M-26NOV131630-30"
FROZEN = "2026-11-13T21:20:00+00:00"                 # the journal freeze, minute 5


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


def _ticks(prob=0.60, ask=0.51, bid=0.49, minutes=(1, 2, 3, 4, 5)):
    return [{"series": "KXWTI15M", "close_time": CLOSE.isoformat(),
             "elapsed_min": float(m) + 0.1, "prob_up": prob,
             "yes_bid": bid, "yes_ask": ask, "price": 100.0} for m in minutes]


def _patch_pass(monkeypatch, *, targets, ticks, settlements, forecasts=None):
    monkeypatch.setattr(tracking, "fetch_targets",
                        lambda supa, family, since, until: targets.get(family, []))
    monkeypatch.setattr(tracking, "fetch_ticks",
                        lambda supa, series, close_times: ticks)
    monkeypatch.setattr(tracking.store, "fetch_settlements",
                        lambda supa, names: settlements)
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: (forecasts or {}).get(f, []))


def _wti(targets, forecasts=None):
    return ({"oil_wti_15m": targets},
            {"oil_wti_15m": forecasts or
             [{"target": targets[0]["target"], "probability": 0.60, "frozen_at": FROZEN,
               "payload": {"yes_ask": 0.51, "yes_bid": 0.49}}]})


def test_shadow_writes_only_its_own_tagged_grid(monkeypatch):
    targets, forecasts = _wti([{"target": TARGET, "cutoff_at": CLOSE.isoformat()}])
    asked = []
    monkeypatch.setattr(tracking, "fetch_targets",
                        lambda supa, family, since, until: asked.append(family) or targets.get(family, []))
    monkeypatch.setattr(tracking, "fetch_ticks", lambda supa, s, c: _ticks())
    monkeypatch.setattr(tracking.store, "fetch_settlements", lambda supa, n: {TARGET: 1})
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: forecasts.get(f, []))
    supa = FakeSupa()
    out = shadow.record_shadow(supa, datetime(2026, 11, 14, tzinfo=UTC))
    rows = supa.tables[shadow.SHADOW_TABLE]
    assert out["windows"] == 1 and len(rows) == 10
    assert {(r["offset_min"], r["bar"]) for r in rows} == \
        {(k, b) for k in (1, 2, 3, 4, 5) for b in (0.05, 0.10)}
    assert all(r["gate_version"] == "v2-oil-shadow" for r in rows)
    assert all(r["series"] == "KXWTI15M" for r in rows)
    # Gas is never asked for: the variant is oil-only.
    assert "natgas_15m" not in asked
    # Nothing lands in the v1 decisions table.
    assert rule.DECISIONS_TABLE not in supa.tables
    # A second pass upserts the same ten rows, never twenty.
    shadow.record_shadow(supa, datetime(2026, 11, 14, tzinfo=UTC))
    assert len(supa.tables[shadow.SHADOW_TABLE]) == 10


def test_shadow_ignores_windows_opened_before_the_preregistration(monkeypatch):
    old_open = datetime(2026, 11, 9, 18, 45, tzinfo=UTC)  # opens before 19:00Z, closes at it
    targets = {"oil_wti_15m": [{"target": "kalshi:OLD", "cutoff_at": "2026-11-09T19:00:00+00:00"}]}
    _patch_pass(monkeypatch, targets=targets, ticks=[], settlements={"kalshi:OLD": 1},
                forecasts={"oil_wti_15m": []})
    assert old_open < datetime.fromisoformat(shadow.PREREG_AT)
    supa = FakeSupa()
    out = shadow.record_shadow(supa, datetime(2026, 11, 14, tzinfo=UTC))
    assert out["windows"] == 0
    assert shadow.SHADOW_TABLE not in supa.tables


def test_tape_never_counts_and_missing_minutes_are_named(monkeypatch):
    targets, forecasts = _wti([{"target": TARGET, "cutoff_at": CLOSE.isoformat()}])
    # Ticks exist only around minute 3: minutes 1, 2, 4, 5 have no live read.
    _patch_pass(monkeypatch, targets=targets, forecasts=forecasts,
                ticks=_ticks(minutes=(3,)), settlements={TARGET: 1})
    supa = FakeSupa()
    shadow.record_shadow(supa, datetime(2026, 11, 14, tzinfo=UTC))
    rows = {(r["offset_min"], r["bar"]): r for r in supa.tables[shadow.SHADOW_TABLE]}
    variant = rows[(1, 0.05)]
    assert variant["action"] == "skip" and variant["reason"] == "no_tick"
    assert rows[(3, 0.05)]["action"] == "buy"  # the minute-3 tick is real and tradable
    assert rows[(3, 0.10)]["reason"] == "no_edge"


def test_tick_without_quotes_is_no_quote_not_a_buy(monkeypatch):
    targets, forecasts = _wti([{"target": TARGET, "cutoff_at": CLOSE.isoformat()}])
    bare = [{"series": "KXWTI15M", "close_time": CLOSE.isoformat(), "elapsed_min": 1.1,
             "prob_up": 0.95, "yes_bid": None, "yes_ask": None, "price": 100.0}]
    _patch_pass(monkeypatch, targets=targets, forecasts=forecasts, ticks=bare,
                settlements={TARGET: 1})
    supa = FakeSupa()
    shadow.record_shadow(supa, datetime(2026, 11, 14, tzinfo=UTC))
    rows = {(r["offset_min"], r["bar"]): r for r in supa.tables[shadow.SHADOW_TABLE]}
    assert rows[(1, 0.05)]["action"] == "skip" and rows[(1, 0.05)]["reason"] == "no_quote"


def test_halt_parity_with_the_live_rule(monkeypatch):
    halt_close = "2026-11-13T22:00:00+00:00"   # freeze 21:50Z = 16:50 ET, inside the halt
    targets = {"oil_wti_15m": [{"target": "kalshi:HALT", "cutoff_at": halt_close}]}
    forecasts = {"oil_wti_15m": [
        {"target": "kalshi:HALT", "probability": 0.95, "frozen_at": "2026-11-13T21:50:00+00:00",
         "payload": {"yes_ask": 0.50, "yes_bid": 0.48}}]}
    ticks = [dict(t, close_time=halt_close) for t in _ticks(prob=0.95, ask=0.50, bid=0.48)]
    _patch_pass(monkeypatch, targets=targets, forecasts=forecasts, ticks=ticks,
                settlements={"kalshi:HALT": 1})
    supa = FakeSupa()
    shadow.record_shadow(supa, datetime(2026, 11, 14, tzinfo=UTC))
    rows = supa.tables[shadow.SHADOW_TABLE]
    assert len(rows) == 10
    assert all(r["action"] == "skip" and r["reason"] == "halt" for r in rows)


def test_criterion_needs_all_three_legs():
    assert shadow.criterion_met(150, 0.01, 0.01)
    assert not shadow.criterion_met(149, 0.30, 0.30)     # count leg
    assert not shadow.criterion_met(200, 0.0, 0.30)      # shadow low95 leg (must be > 0)
    assert not shadow.criterion_met(200, 0.30, -0.01)    # paired-delta leg
    assert not shadow.criterion_met(200, None, 0.30)     # an unmeasurable leg never passes


def _seed_evaluation(supa, *, n_trades=160, shadow_pnl=0.6853, live_buys=False):
    """n settled fresh oil windows: shadow variant buys on all of them; the
    live rule skips (or takes the identical buy, when live_buys)."""
    base = datetime(2026, 11, 10, tzinfo=UTC)
    for i in range(n_trades):
        open_ = base + timedelta(minutes=15 * i)
        target = f"kalshi:W{i}"
        supa.tables.setdefault(shadow.SHADOW_TABLE, []).append({
            "series": "KXWTI15M", "target": target, "window_open": open_.isoformat(),
            "offset_min": 1, "bar": 0.05, "gate_version": "v2-oil-shadow",
            "session": "open", "action": "buy", "side": "yes", "cost": 0.30,
            "outcome": 1, "pnl": shadow_pnl})
        supa.tables.setdefault(rule.DECISIONS_TABLE, []).append({
            "series": "KXWTI15M", "target": target, "gate_version": "v1",
            "session": "open", "action": "buy" if live_buys else "skip",
            "outcome": 1, "pnl": shadow_pnl if live_buys else None})


def test_evaluation_promotes_once_with_an_audit_row():
    supa = FakeSupa()
    _seed_evaluation(supa)
    now = datetime(2026, 11, 16, tzinfo=UTC)
    out = shadow.evaluate_promotion(supa, now)
    assert out["criterion_met"] and out["promoted"]
    assert out["trades"] == 160 and out["paired_low95"] > 0
    promos = supa.tables[shadow.PROMOTIONS_TABLE]
    assert len(promos) == 1 and promos[0]["kind"] == "promotion"
    assert promos[0]["to_version"] == "v2-oil" and promos[0]["evidence"]["trades"] == 160
    assert shadow.current_state(supa) == "v2-oil"
    # A later evaluation never promotes twice.
    out2 = shadow.evaluate_promotion(supa, now + timedelta(days=1))
    assert not out2["promoted"] and len(supa.tables[shadow.PROMOTIONS_TABLE]) == 1


def test_evaluation_never_promotes_on_a_failing_leg():
    for seed in ({"n_trades": 100}, {"shadow_pnl": -0.20}, {"live_buys": True}):
        supa = FakeSupa()
        _seed_evaluation(supa, **seed)
        out = shadow.evaluate_promotion(supa, datetime(2026, 11, 16, tzinfo=UTC))
        assert not out["criterion_met"] and not out["promoted"], seed
        assert shadow.PROMOTIONS_TABLE not in supa.tables
        assert shadow.current_state(supa) == "v1"


def test_daily_evaluation_runs_once_a_day():
    supa = FakeSupa()
    _seed_evaluation(supa, n_trades=10)
    now = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
    shadow.evaluate_daily(supa, now)
    again = shadow.evaluate_daily(supa, now + timedelta(hours=3))
    assert again.get("skipped") == "already_evaluated_today"
    assert len(supa.tables[shadow.EVALS_TABLE]) == 1
    shadow.evaluate_daily(supa, now + timedelta(days=1))
    assert len(supa.tables[shadow.EVALS_TABLE]) == 2


def test_reversal_restores_v1_in_one_action():
    supa = FakeSupa()
    _seed_evaluation(supa)
    now = datetime(2026, 11, 16, tzinfo=UTC)
    shadow.evaluate_promotion(supa, now)
    assert shadow.current_state(supa) == "v2-oil"
    shadow.revert_promotion(supa, now + timedelta(days=2), reason="test")
    assert shadow.current_state(supa) == "v1"
    kinds = [r["kind"] for r in supa.tables[shadow.PROMOTIONS_TABLE]]
    assert kinds == ["promotion", "reversal"]


def test_decisions_summary_never_counts_shadow_rows(monkeypatch):
    shadow_rows = [{"action": "buy", "reason": None} for _ in range(7)]
    decision_rows = [{"action": "buy", "reason": None}, {"action": "skip", "reason": "halt"}]

    def select_all(supa, table, build, order):
        return shadow_rows if table == shadow.SHADOW_TABLE else decision_rows

    monkeypatch.setattr(rule.store, "select_all", select_all)
    out = rule._decisions_summary(FakeSupa())
    assert out == {"recorded": 2, "buy": 1, "skip": 1, "by_reason": {"halt": 1}}


def test_summary_opens_empty_and_unpromoted():
    out = shadow.summary(FakeSupa())
    assert out["gate_version"] == "v2-oil-shadow"
    assert out["prereg_at"] == shadow.PREREG_AT
    assert out["fresh"]["trades"] == 0
    assert out["promotion"]["state"] == "v1" and not out["promotion"]["met"]
    assert out["promotion"]["criterion"] == {
        "min_trades": shadow.PROMOTION_MIN_TRADES, "shadow_low95_above": 0,
        "paired_low95_above": 0}


def _patch_decisions(monkeypatch, *, targets, forecasts, settlements, ticks, state):
    monkeypatch.setattr(tracking, "fetch_targets",
                        lambda supa, family, since, until: targets.get(family, []))
    monkeypatch.setattr(tracking, "fetch_ticks",
                        lambda supa, series, close_times: ticks)
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: forecasts.get(f, []))
    monkeypatch.setattr(tracking.store, "fetch_settlements",
                        lambda supa, targets: settlements)
    monkeypatch.setattr(tracking, "_candles_or_empty", lambda *a: [])
    import tradehub.fifteen_shadow as sh
    monkeypatch.setattr(sh, "current_state", lambda supa: state)
    monkeypatch.setattr(sh, "promoted_at", lambda supa: "2026-11-13T00:00:00+00:00")


def test_promoted_oil_decisions_come_from_minute_one(monkeypatch):
    # The forecast read would SKIP (0.55 vs ask 0.50 nets under the 0.10 bar);
    # the minute-1 tick (0.80 vs the same quotes) clears the 0.05 bar easily.
    forecasts = {"oil_wti_15m": [
        {"target": TARGET, "probability": 0.55, "frozen_at": FROZEN,
         "payload": {"yes_ask": 0.50, "yes_bid": 0.48}}]}
    ticks = [{"series": "KXWTI15M", "close_time": CLOSE.isoformat(), "elapsed_min": 1.1,
              "prob_up": 0.80, "yes_bid": 0.48, "yes_ask": 0.50, "price": 100.0}]
    _patch_decisions(monkeypatch,
                     targets={"oil_wti_15m": [{"target": TARGET, "cutoff_at": CLOSE.isoformat()}]},
                     forecasts=forecasts, settlements={TARGET: 1}, ticks=ticks, state="v2-oil")
    supa = tracking_Capture()
    tracking.record_decisions(supa, datetime(2026, 11, 14, tzinfo=UTC),
                              candles_fn=lambda *a: [])
    row = supa.rows[TARGET]
    assert row["gate_version"] == "v2-oil"
    assert row["action"] == "buy" and row["cost"] == 0.50 and row["model_prob"] == 0.80
    assert row["pnl"] == rule.pnl("yes", 0.50, 1)


def test_unpromoted_decisions_stay_v1_and_stamped(monkeypatch):
    forecasts = {"oil_wti_15m": [
        {"target": TARGET, "probability": 0.55, "frozen_at": FROZEN,
         "payload": {"yes_ask": 0.50, "yes_bid": 0.48}}]}
    _patch_decisions(monkeypatch,
                     targets={"oil_wti_15m": [{"target": TARGET, "cutoff_at": CLOSE.isoformat()}]},
                     forecasts=forecasts, settlements={TARGET: 1}, ticks=[], state="v1")
    supa = tracking_Capture()
    tracking.record_decisions(supa, datetime(2026, 11, 14, tzinfo=UTC),
                              candles_fn=lambda *a: [])
    row = supa.rows[TARGET]
    assert row["gate_version"] == "v1" and row["action"] == "skip" and row["reason"] == "no_edge"


class tracking_Capture:
    """The tracking tests' upsert capture, keyed (series, target)."""

    def __init__(self):
        self.tables: dict[str, dict] = {}

    def table(self, name):
        supa = self

        class _T:
            def upsert(self, rows, on_conflict=None):
                keys = on_conflict.split(",")
                tbl = supa.tables.setdefault(name, {})
                for r in rows:
                    tbl[tuple(r[k] for k in keys)] = dict(r)
                return self

            def execute(self):
                return type("R", (), {"data": []})()

        return _T()

    @property
    def rows(self):
        return {k[1]: v for k, v in self.tables[rule.DECISIONS_TABLE].items()}
