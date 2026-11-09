"""Picker v2 (spec 2026-11-09, options A + B + D): the 15-point bar on
calibrated probabilities, the fee inside the ranking, the T-10 second
freeze, and freezes that store what they saw."""

from datetime import UTC, datetime, timedelta

from tradehub.oil_calibration import CalSample
from tradehub.oil_itm import record, run
from tradehub.oil_live import pick_best_strike_v2

IDENT = lambda p: p  # noqa: E731


def _row(strike, ours, bid, ask):
    return {"strike": strike, "ours": ours, "market": (bid + ask) / 2,
            "yes_bid": bid, "yes_ask": ask}


# --- the pick ---------------------------------------------------------


def test_the_bar_is_fifteen_points_on_the_calibrated_probability():
    rows = [_row(88.5, 0.75, 0.57, 0.58)]  # raw gross edge 17: v1 takes it
    pick, _ = pick_best_strike_v2(rows, IDENT)
    assert pick is not None and pick["edge_pts"] == 17.0
    pick, closest = pick_best_strike_v2(rows, lambda p: p - 0.10)
    assert pick is None and closest["edge_pts"] == 7.0  # calibrated 0.65 vs cost 0.58


def test_calibration_can_promote_a_pick_the_raw_rule_missed():
    rows = [_row(88.5, 0.55, 0.49, 0.50)]  # raw gross edge only 5
    pick, _ = pick_best_strike_v2(rows, lambda p: p + 0.12)
    assert pick is not None and pick["prob"] == 0.67 and pick["prob_raw"] == 0.55


def test_ranking_is_by_net_edge_with_the_fee_inside():
    # Near-equal gross edges; the dearer contract keeps more after the fee
    # curve (fee peaks mid-band), so net ranking must pick it.
    rows = [_row(88.5, 0.70, 0.49, 0.50),   # gross 20.0, net 18.25
            _row(89.5, 0.899, 0.69, 0.70)]  # gross 19.9, net 18.43
    pick, _ = pick_best_strike_v2(rows, IDENT)
    assert pick["strike"] == 89.5 and pick["net_pts"] == 18.43


def test_the_no_side_calibrates_as_one_minus_the_yes_map():
    rows = [_row(88.5, 0.10, 0.25, 0.27)]  # NO: prob 0.90 at cost 0.75 -> gross 15.0
    pick, _ = pick_best_strike_v2(rows, IDENT)
    assert pick["side"] == "no" and pick["prob"] == 0.90 and pick["cost"] == 0.75
    pick, _ = pick_best_strike_v2(rows, lambda p: p + 0.05)  # yes 0.15 -> NO prob 0.85
    assert pick is None


def test_cost_band_and_spread_filters_still_apply():
    rows = [_row(88.5, 0.99, 0.84, 0.86),   # cost outside the 0.20-0.80 band
            _row(89.5, 0.99, 0.40, 0.52)]   # spread 0.12 over the 0.08 cap
    pick, closest = pick_best_strike_v2(rows, IDENT)
    assert pick is None and closest is None


# --- the freezes ------------------------------------------------------

NOW = datetime(2026, 11, 9, 17, 30, tzinfo=UTC)
EV30 = "KXWTIH-26NOV0913"   # closes 18:00 UTC, 30 minutes after NOW
EV10 = "KXWTIH-26NOV0912T"  # the fake imminent event for the T-10 discovery
ROWS = [{"strike": 88.5, "ours": 0.75, "market": 0.575, "yes_bid": 0.57, "yes_ask": 0.58}]


class _Q:
    def __init__(self, store, name):
        self.store, self.name, self.filters, self.op, self.payload = store, name, {}, None, None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self.op == "insert":
            rows.append(dict(self.payload, id=len(rows) + 1, settled=False))
            return type("R", (), {"data": [self.payload]})()
        if self.op == "update":
            for row in rows:
                if all(row.get(k) == v for k, v in self.filters.items()):
                    row.update(self.payload)
            return type("R", (), {"data": []})()
        data = [dict(r) for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
        return type("R", (), {"data": data})()


class _Fake:
    def __init__(self):
        self.store: dict = {}

    def table(self, name):
        return _Q(self.store, name)


class _Mkt:
    def __init__(self, event, close):
        self.event_ticker, self.close_time = event, close


class _LM:
    def __init__(self, event, close):
        self.market = _Mkt(event, close)


class _Live:
    def __init__(self, settled=()):
        self._settled = list(settled)

    def settled_values_recent(self, _series, _n):
        return self._settled

    def open_markets(self, _series):
        return [_LM(EV10, NOW + timedelta(minutes=10)),
                _LM(EV30, NOW + timedelta(minutes=30))]


def _view(event, minutes, rows=ROWS):
    return {"state": "live", "event": event, "minutes_to_close": minutes,
            "live_price": 88.4, "sigma_h": 0.42,
            "close_time": (NOW + timedelta(minutes=minutes)).isoformat(),
            "rows": rows, "best": None}


def _ladder(_now):
    return _view(EV30, 30.0)


def _event_ladder(_now, event_ticker=None):
    return _view(event_ticker, 10.0)


_NO_SAMPLES = lambda supa: []  # noqa: E731


def test_a_v2_freeze_stores_the_full_instrumentation():
    fake = _Fake()
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder, samples_fn=_NO_SAMPLES)
    assert out["frozen"] == EV30
    (row,) = fake.store["oil_itm_lines"]
    assert row["picker_version"] == "v2" and row["freeze_kind"] == "T-30"
    assert row["ours"] == 0.75 and row["ours_cal"] == 0.75  # identity map on empty history
    assert row["cost"] == 0.58 and row["edge_pts"] == 17.0 and row["edge_net_pts"] == 15.29
    assert row["yes_bid"] == 0.57 and row["yes_ask"] == 0.58
    assert row["sigma_h"] == 0.42 and row["minutes_to_close"] == 30.0
    assert row["calib_map_version"].startswith("oilcal-identity")
    assert row["side"] == "yes" and row["strike"] == 88.5 and row["live_price"] == 88.4


def test_calibration_can_veto_a_pick_that_clears_the_raw_bar():
    # The model's 0.75s realized 50% over 1,200 settled rows / 50 events:
    # calibrated gross edge is deeply negative, so nothing freezes.
    closes = [datetime(2026, 11, 8, tzinfo=UTC) + timedelta(hours=i) for i in range(50)]
    samples = [CalSample(0.75, i % 2 == 0, closes[i % 50]) for i in range(1200)]
    fake = _Fake()
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder, samples_fn=lambda supa: samples)
    assert out["frozen"] is None and fake.store.get("oil_itm_lines", []) == []


def test_the_t10_freeze_is_its_own_row_and_a_legacy_row_never_blocks_v2():
    fake = _Fake()
    fake.store["oil_itm_lines"] = [
        {"id": 7, "event_ticker": EV30, "strike": 88.0, "ours": 0.6, "market": 0.5,
         "settled": False, "frozen_at": NOW.isoformat()}]  # a legacy v1 row
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder,
              event_ladder_fn=_event_ladder, samples_fn=_NO_SAMPLES)
    assert out["frozen"] == EV30 and out["frozen_t10"] == EV10
    kinds = sorted((r["event_ticker"], r.get("freeze_kind")) for r in fake.store["oil_itm_lines"]
                   if r.get("picker_version") == "v2")
    assert kinds == [(EV10, "T-10"), (EV30, "T-30")]
    # A second run inside both windows freezes nothing new.
    out = run(fake, now=NOW, live=_Live(), ladder_fn=_ladder,
              event_ladder_fn=_event_ladder, samples_fn=_NO_SAMPLES)
    assert out["frozen"] is None and out["frozen_t10"] is None
    assert len(fake.store["oil_itm_lines"]) == 3


def test_v2_rows_grade_and_the_record_splits_by_segment():
    from tradehub.backtest.pit import Observation

    fake = _Fake()
    run(fake, now=NOW, live=_Live(), ladder_fn=_ladder,
        event_ladder_fn=_event_ladder, samples_fn=_NO_SAMPLES)
    live = _Live(settled=[Observation(EV30, 91.20, NOW)])
    out = run(fake, now=NOW, live=live, ladder_fn=lambda _n: _view(EV30, 50.0),
              samples_fn=_NO_SAMPLES)
    assert out["graded"] == 1  # 91.20 settles over the 88.5 strike: the YES pick hits
    seg = record(fake)["by_segment"]
    assert seg["v2_T-30"] == {"frozen": 1, "settled": 1, "hits": 1,
                              "hit_rate": 1.0, "net_per_contract": 0.4029}
    assert seg["v2_T-10"]["frozen"] == 1 and seg["v2_T-10"]["settled"] == 0
    assert seg["legacy"]["frozen"] == 0
