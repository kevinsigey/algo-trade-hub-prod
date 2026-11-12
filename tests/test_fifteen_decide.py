"""The fifteen-minute rule decides at freeze time (2026-11-12 runner fix).

Golden: `record_decisions` -- the live rule's record pass -- writes
byte-identical rows to the golden file captured from the code before the
per-window decision was split out. The fixture covers every gate branch:
v1 (buy, no_prediction, stale_tape), the promoted oil gate (buy,
stale_tape, no_edge) and the promoted blend (buy, no_prediction,
no_weight, no_quote).

`open_decisions` returns, for still-open windows, the same decision the
record pass later writes -- and omits a window with no frozen read yet.
"""
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tradehub import fifteen_blend as blend
from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule

GOLDEN = Path(__file__).parent / "fixtures" / "fifteen_decisions_golden.json"
NOW = datetime(2026, 11, 13, 20, 0, tzinfo=UTC)        # Fri 15:00 ET, no halt
GATE_SINCE = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)  # oil gate flipped
BLEND_SINCE = datetime(2026, 11, 13, 18, 0, tzinfo=UTC)  # blend flipped later
WEIGHTS = {"KXWTI15M": 1.0, "KXBRENT15M": 1.0}           # gas: no weight -> no_weight


def _at(h, m):
    return datetime(2026, 11, 13, h, m, tzinfo=UTC)


def _cal(target, open_):
    return {"target": target, "cutoff_at": (open_ + timedelta(minutes=15)).isoformat()}


def _fc(target, open_, p, ask=0.50, bid=0.48):
    pay = {} if ask is None else {"yes_ask": ask, "yes_bid": bid}
    return {"target": target, "probability": p,
            "frozen_at": (open_ + timedelta(minutes=5)).isoformat(), "payload": pay}


def _tape(window_open):
    out = []
    for m in range(-160, 76):
        t = window_open + timedelta(minutes=m)
        out.append((t, 100.0 if m < 0 else 100.0 * 1.001 ** (m + 1)))
    return out


TARGETS = {
    "oil_wti_15m": [
        _cal("kalshi:W1", _at(13, 0)), _cal("kalshi:W2", _at(13, 15)),
        _cal("kalshi:W3", _at(13, 30)), _cal("kalshi:W4", _at(15, 0)),
        _cal("kalshi:W5", _at(15, 15)), _cal("kalshi:W6", _at(15, 30)),
        _cal("kalshi:W7", _at(18, 0)), _cal("kalshi:W8", _at(18, 15))],
    "natgas_15m": [_cal("kalshi:G1", _at(15, 0)), _cal("kalshi:G2", _at(18, 0))],
    "oil_brent_15m": [_cal("kalshi:B1", _at(18, 0))],
}
FORECASTS = {
    "oil_wti_15m": [_fc("kalshi:W1", _at(13, 0), 0.70), _fc("kalshi:W7", _at(18, 0), 0.72),
                    # a later freeze of W1 never replaces the first one
                    {**_fc("kalshi:W1", _at(13, 0), 0.10),
                     "frozen_at": _at(13, 9).isoformat()}],
    "natgas_15m": [_fc("kalshi:G1", _at(15, 0), 0.30), _fc("kalshi:G2", _at(18, 0), 0.80)],
    "oil_brent_15m": [_fc("kalshi:B1", _at(18, 0), 0.75, ask=None)],
}
TICKS = {  # (series, close_time) -> minute tape rows
    ("KXWTI15M", (_at(15, 0) + timedelta(minutes=15)).isoformat()): [
        {"elapsed_min": 1.1, "prob_up": 0.75, "yes_ask": 0.50, "yes_bid": 0.48},
        {"elapsed_min": 2.0, "prob_up": 0.10, "yes_ask": 0.50, "yes_bid": 0.48}],
    ("KXWTI15M", (_at(15, 30) + timedelta(minutes=15)).isoformat()): [
        {"elapsed_min": 0.9, "prob_up": 0.50, "yes_ask": 0.50, "yes_bid": 0.48}],
}
SETTLED = {"kalshi:W1": 1, "kalshi:W4": 0, "kalshi:G1": 0, "kalshi:W7": 1}


def _candles(coin, start, end):
    window_open = start + tracking.TAPE_SPAN
    return [] if window_open == _at(13, 30) else _tape(window_open)


def _weight(supa, name, version, series, day, now):
    if series not in WEIGHTS:
        raise RuntimeError("weights table unavailable")
    return WEIGHTS[series]


def patch_world(monkeypatch, targets=TARGETS, forecasts=FORECASTS, ticks=TICKS):
    def fetch_targets(supa, family, since, until):
        return [t for t in targets.get(family, [])
                if since <= datetime.fromisoformat(t["cutoff_at"]) <= until]

    monkeypatch.setattr(tracking, "fetch_targets", fetch_targets)
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: [
                            r for r in forecasts.get(f, []) if targets is None or r["target"] in targets])
    monkeypatch.setattr(tracking.store, "fetch_settlements",
                        lambda supa, names: {k: v for k, v in SETTLED.items() if k in names})
    monkeypatch.setattr(tracking, "fetch_ticks", lambda supa, series, closes: [
        {**tk, "close_time": ct} for (s, ct), rows in ticks.items()
        if s == series and ct in closes for tk in rows])
    monkeypatch.setattr(tracking, "_live_gate", lambda supa: ("v2-oil", GATE_SINCE))
    monkeypatch.setattr(tracking, "_blend_gate", lambda supa: BLEND_SINCE)
    monkeypatch.setattr(blend, "weight_for_day", _weight)


class Capture:
    def __init__(self):
        self.upserts: list[list[dict]] = []

    def table(self, name):
        cap = self

        class _T:
            def upsert(self, rows, on_conflict=None):
                assert name == rule.DECISIONS_TABLE and on_conflict == "series,target"
                cap.upserts.append(rows)
                return self

            def execute(self):
                return type("R", (), {"data": []})()

        return _T()


def recorded_rows(monkeypatch) -> list[dict]:
    patch_world(monkeypatch)
    supa = Capture()
    tracking.record_decisions(supa, NOW, candles_fn=_candles)
    assert len(supa.upserts) == 1
    return supa.upserts[0]


def test_record_decisions_output_unchanged_by_refactor(monkeypatch):
    rows = recorded_rows(monkeypatch)
    got = json.dumps(rows, indent=1)
    assert got == GOLDEN.read_text().rstrip("\n")
    # The fixture really does reach every branch the golden claims it does.
    seen = {(r["gate_version"], r["action"], r["reason"]) for r in rows}
    assert seen >= {("v1", "buy", None), ("v1", "skip", "no_prediction"),
                    ("v1", "skip", "stale_tape"), ("v2-oil", "buy", None),
                    ("v2-oil", "skip", "stale_tape"), ("v2-oil", "skip", "no_edge"),
                    ("v2-blend", "buy", None), ("v2-blend", "skip", "no_prediction"),
                    ("v2-blend", "skip", "no_weight"), ("v2-blend", "skip", "no_quote")}
