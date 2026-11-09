"""The fifteen-minute rule's persisted tracking (amendment 2026-11-08): one
decision row per targeted window -- buys and named skips alike -- and a
per-offset shadow track for every settled window, so the entry-time question
can be answered from data instead of argued about.
"""
from datetime import UTC, datetime, timedelta

from tradehub import fifteen_tracking as tracking
from tradehub import oil_fifteen_rule as rule

OPEN = datetime(2026, 11, 13, 21, 15, tzinfo=UTC)   # a Friday window, 16:15 ET
CLOSE = OPEN + timedelta(minutes=15)
TARGET = "kalshi:KXWTI15M-26NOV131630-30"


def tape(open_: datetime = OPEN, *, flat: bool = False):
    """1-minute (open time, close) candles from 160 minutes before the window
    to 75 after: flat at 100 before the open, rising 0.1% a minute inside it."""
    out = []
    for m in range(-160, 76):
        t = open_ + timedelta(minutes=m)
        close = 100.0 if (flat or m < 0) else 100.0 * 1.001 ** (m + 1)
        out.append((t, close))
    return out


class CaptureSupa:
    """Applies upserts into dicts keyed by the conflict columns, like the DB."""

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


def _patch_reads(monkeypatch, *, targets, forecasts, settlements):
    monkeypatch.setattr(tracking, "fetch_targets",
                        lambda supa, family, since, until: targets.get(family, []))
    monkeypatch.setattr(tracking.store, "fetch_forecasts",
                        lambda supa, f, v, targets=None: forecasts.get(f, []))
    monkeypatch.setattr(tracking.store, "fetch_settlements",
                        lambda supa, targets: settlements)


def test_decisions_record_buys_and_named_skips(monkeypatch):
    halt_open = datetime(2026, 11, 13, 21, 45, tzinfo=UTC)  # frozen 16:50 ET
    targets = {"oil_wti_15m": [
        {"target": "kalshi:BUY", "cutoff_at": CLOSE.isoformat()},
        {"target": "kalshi:THIN", "cutoff_at": CLOSE.isoformat()},
        {"target": "kalshi:NOPRED", "cutoff_at": CLOSE.isoformat()},
        {"target": "kalshi:STALE", "cutoff_at": "2026-11-13T22:30:00+00:00"},
        {"target": "kalshi:HALT", "cutoff_at": (halt_open + timedelta(minutes=15)).isoformat()},
    ]}
    forecasts = {"oil_wti_15m": [
        {"target": "kalshi:BUY", "probability": 0.63, "frozen_at": "2026-11-13T21:20:00+00:00",
         "payload": {"yes_ask": 0.51, "yes_bid": 0.49}},
        {"target": "kalshi:THIN", "probability": 0.55, "frozen_at": "2026-11-13T21:20:00+00:00",
         "payload": {"yes_ask": 0.50, "yes_bid": 0.48}},
        {"target": "kalshi:HALT", "probability": 0.90, "frozen_at": "2026-11-13T21:50:00+00:00",
         "payload": {"yes_ask": 0.50, "yes_bid": 0.48}},
    ]}
    _patch_reads(monkeypatch, targets=targets, forecasts=forecasts,
                 settlements={"kalshi:BUY": 1, "kalshi:THIN": 0})

    def candles(coin, start, end):
        # The recheck asks for the tape around each window's freeze moment;
        # STALE's window (an hour later) gets nothing back.
        return tape() if end <= datetime(2026, 11, 13, 21, 30, tzinfo=UTC) else []

    supa = CaptureSupa()
    now = datetime(2026, 11, 14, tzinfo=UTC)
    out = tracking.record_decisions(supa, now, candles_fn=candles)
    rows = {k[1]: v for k, v in supa.tables[rule.DECISIONS_TABLE].items()}
    assert out["windows"] == 5
    buy = rows["kalshi:BUY"]
    assert buy["action"] == "buy" and buy["side"] == "yes" and buy["cost"] == 0.51
    assert buy["outcome"] == 1 and buy["pnl"] == rule.pnl("yes", 0.51, 1)
    assert buy["session"] == "open"
    thin = rows["kalshi:THIN"]
    assert thin["action"] == "skip" and thin["reason"] == "no_edge" and thin["pnl"] is None
    assert rows["kalshi:NOPRED"]["reason"] == "no_prediction"
    assert rows["kalshi:STALE"]["reason"] == "stale_tape"
    assert rows["kalshi:HALT"]["reason"] == "halt"
    # A second pass over the same windows upserts the same five rows, never ten.
    tracking.record_decisions(supa, now, candles_fn=candles)
    assert len(supa.tables[rule.DECISIONS_TABLE]) == 5


def test_offsets_score_every_minute_of_a_settled_window(monkeypatch):
    _patch_reads(monkeypatch,
                 targets={"oil_wti_15m": [{"target": TARGET, "cutoff_at": CLOSE.isoformat()}]},
                 forecasts={"oil_wti_15m": [
                     {"target": TARGET, "probability": 0.9, "frozen_at": "2026-11-13T21:20:00+00:00",
                      "payload": {"yes_ask": 0.63, "yes_bid": 0.60, "open_price": 100.0}}]},
                 settlements={TARGET: 1})
    ticks = [
        {"series": "KXWTI15M", "ticker": "KXWTI15M-26NOV131630-30", "close_time": CLOSE.isoformat(),
         "elapsed_min": 5.2, "prob_up": 0.9, "yes_bid": 0.60, "yes_ask": 0.63, "price": 100.5, "open_price": 100.0},
        {"series": "KXWTI15M", "ticker": "KXWTI15M-26NOV131630-30", "close_time": CLOSE.isoformat(),
         "elapsed_min": 9.7, "prob_up": 0.95, "yes_bid": 0.80, "yes_ask": 0.83, "price": 101.0, "open_price": 100.0},
    ]
    monkeypatch.setattr(tracking, "fetch_ticks", lambda supa, series, close_times: ticks)
    monkeypatch.setattr(tracking, "fetch_tracked_offsets", lambda supa, targets: {})
    supa = CaptureSupa()
    out = tracking.record_offsets(supa, datetime(2026, 11, 14, tzinfo=UTC),
                                  candles_fn=lambda coin, s, e: tape())
    assert out["windows"] == 1 and out["rows"] == 16
    rows = {k[2]: v for k, v in supa.tables[rule.OFFSETS_TABLE].items()}
    assert sorted(rows) == list(range(16))
    five = rows[5]
    assert five["prob_source"] == "tick" and five["prob_up"] == 0.9
    assert five["side"] == "yes" and five["side_cost"] == 0.63
    assert five["pnl"] == rule.pnl("yes", 0.63, 1) and five["outcome"] == 1
    ten = rows[10]
    assert ten["prob_source"] == "tick" and ten["pnl"] == rule.pnl("yes", 0.83, 1)
    zero = rows[0]
    assert zero["prob_source"] == "tape" and zero["prob_up"] == 0.5 and zero["pnl"] is None
    assert zero["price"] == 100.0
    # The settlement and +60m references ride on every row of the window.
    settle = 100.0 * 1.001 ** 15
    assert abs(five["price_at_settle"] - settle) < 1e-9
    assert abs(five["price_at_60m"] - 100.0 * 1.001 ** 60) < 1e-9
    assert abs(five["move_to_settle_bps"] - (settle / five["price"] - 1) * 1e4) < 1e-6


def test_offsets_skip_windows_already_tracked(monkeypatch):
    _patch_reads(monkeypatch,
                 targets={"oil_wti_15m": [{"target": TARGET, "cutoff_at": CLOSE.isoformat()}]},
                 forecasts={"oil_wti_15m": []},
                 settlements={TARGET: 1})
    monkeypatch.setattr(tracking, "fetch_ticks", lambda supa, series, close_times: [])
    monkeypatch.setattr(tracking, "fetch_tracked_offsets",
                        lambda supa, targets: {TARGET: set(range(16))})
    supa = CaptureSupa()
    out = tracking.record_offsets(supa, datetime(2026, 11, 14, tzinfo=UTC),
                                  candles_fn=lambda coin, s, e: tape())
    assert out["windows"] == 0 and rule.OFFSETS_TABLE not in supa.tables
