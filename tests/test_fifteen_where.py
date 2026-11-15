"""Step A (fifteen_where) tests: no look-ahead, matched-window pairing,
fillable filtering, clustered-vs-naive CI width, cell blanking, and the
haircut pass-through (replay pnl is used exactly as stored)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradehub.research.events_calendar import event_feature
from tradehub.research.fifteen_where import build_report, cell, enrich

UTC = timezone.utc


def row(series, close, offset, *, side=None, pnl=None, outcome=1, price=None,
        edge=0.12, cost=0.50, fillable=None, target=None):
    return {"series": series, "target": target or f"{series}-{close.isoformat()}",
            "close_time": close.isoformat(), "offset_min": offset,
            "prob_up": 0.6, "side": side, "side_cost": cost if side else None,
            "edge_net": edge if side else None, "outcome": outcome,
            "pnl": pnl, "price": price, "fillable": fillable}


def window(series, close, outcome, *, trade_offset=None, pnl=0.05, price0=100.0,
           prices=None, fillable=None):
    """One settled window: an untraded row plus, optionally, one trade."""
    rows = [row(series, close, 0, outcome=outcome, price=price0)]
    if trade_offset is not None:
        rows.append(row(series, close, trade_offset, side="yes", pnl=pnl,
                        outcome=outcome, fillable=fillable,
                        price=(prices or {}).get(trade_offset, price0)))
    return rows


def test_cell_blanks_under_30_trades():
    trades = [{"series": "KXWTI15M", "day": "2026-11-06", "pnl_cents": 5.0}
              for _ in range(29)]
    assert cell(trades) is None
    trades.append({"series": "KXWTI15M", "day": "2026-11-07", "pnl_cents": 5.0})
    assert cell(trades)["n"] == 30


def test_clustered_low95_is_wider_than_naive_when_days_correlate():
    # Three days, each day internally identical but days far apart: the
    # naive interval treats 90 rows as independent and is far too tight.
    trades = []
    for day, pnl in (("2026-11-06", 30.0), ("2026-11-07", -20.0), ("2026-11-08", 10.0)):
        trades += [{"series": "KXWTI15M", "day": day, "pnl_cents": pnl}
                   for _ in range(30)]
    got = cell(trades)
    import statistics
    vals = [t["pnl_cents"] for t in trades]
    naive_low = statistics.mean(vals) - 1.96 * statistics.stdev(vals) / len(vals) ** 0.5
    assert got["low95"] is not None and got["low95"] < naive_low


def test_trend_features_ignore_the_future():
    base = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    rows = []
    for k, outcome in ((3, 0), (2, 1), (1, 1)):  # windows closing before
        rows += window("KXGOLD15M", base - timedelta(minutes=15 * k), outcome)
    rows += window("KXGOLD15M", base, 1, trade_offset=5)
    first = enrich(rows, "forward")[0]
    assert first["prev_window"] == "up" and first["side_agrees_last"] == "agrees"
    assert first["trend3"] == "up"
    # Now change the future: the NEXT window's outcome and wild prices,
    # plus a later offset inside the trade's own window.
    rows += window("KXGOLD15M", base + timedelta(minutes=15), 0, price0=1.0)
    rows.append(row("KXGOLD15M", base, 14, outcome=1, price=9999.0))
    second = enrich(rows, "forward")[0]
    assert (second["prev_window"], second["side_agrees_last"], second["trend3"]) == \
           (first["prev_window"], first["side_agrees_last"], first["trend3"])


def test_move_so_far_never_reads_the_60m_fields():
    base = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    rows = window("KXWTI15M", base, 1, trade_offset=5, price0=100.0,
                  prices={5: 101.0})
    # Poison the look-ahead fields: if the code read them, the move
    # would come out 'down' (settle below) instead of 'up'.
    for r in rows:
        r["price_at_60m"] = 50.0
        r["move_to_60m_bps"] = -5000.0
        r["price_at_settle"] = 50.0
    trade = enrich(rows, "replay")[0]
    assert trade["move_so_far"] == "up"


def test_paired_table_uses_matched_windows_only():
    base = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(35):  # matched: minutes 5 and 7 both trade
        close = base + timedelta(minutes=15 * i)
        rows += window("KXWTI15M", close, 1, trade_offset=5, pnl=0.0)
        rows.append(row("KXWTI15M", close, 7, side="yes", pnl=0.10, outcome=1))
    for i in range(40):  # unmatched: minute 7 alone never pairs
        close = base + timedelta(days=2, minutes=15 * i)
        rows += window("KXWTI15M", close, 1, trade_offset=7, pnl=0.99)
    report = build_report(rows, [])
    paired = [p for p in report["views"]["all"]["paired_vs_5"]
              if p["minute"] == 7 and p["series"] == "KXWTI15M"
              and p["source"] == "forward"]
    assert len(paired) == 1 and paired[0]["n_windows"] == 35
    assert paired[0]["cents"] == 10.0


def test_fillable_view_counts_only_fillable_trades():
    base = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    rows = []
    for i in range(35):
        close = base + timedelta(minutes=15 * i)
        rows += window("KXWTI15M", close, 1, trade_offset=5, fillable=True)
    for i in range(35):
        close = base + timedelta(days=2, minutes=15 * i)
        rows += window("KXWTI15M", close, 1, trade_offset=5, fillable=False)
    report = build_report([], rows)
    minute_rows = report["views"]["fillable"]["features"]["minute"]
    five = next(r for r in minute_rows if r["bucket"] == "5")
    assert five["cells"]["POOLED"]["replay"]["n"] == 35
    all_five = next(r for r in report["views"]["all"]["features"]["minute"]
                    if r["bucket"] == "5")
    assert all_five["cells"]["POOLED"]["replay"]["n"] == 70


def test_replay_pnl_passes_through_with_haircut_already_in():
    # A0 stored replay pnl already nets the 1c haircut (it is inside
    # side_cost). The study must not haircut a second time.
    trades = [{"series": "KXGOLD15M", "day": f"2026-11-{d:02d}", "pnl_cents": 41.28}
              for d in range(1, 31) for _ in range(2)]
    assert cell(trades)["cents"] == 41.28


def test_event_feature_flags_the_published_schedule():
    cpi = event_feature("KXGOLD15M", datetime(2026, 11, 10, 13, 45, tzinfo=UTC))
    assert cpi["event_kind"] == "cpi" and cpi["event_within_15"]  # 08:45 ET
    eia = event_feature("KXWTI15M", datetime(2026, 11, 11, 15, 30, tzinfo=UTC))
    assert eia["event_kind"] == "eia_petroleum"  # Wed 10:30 ET
    gas = event_feature("KXNATGAS15M", datetime(2026, 11, 12, 15, 30, tzinfo=UTC))
    assert gas["event_kind"] == "eia_gas_storage"  # Thu 10:30 ET
    quiet = event_feature("KXWTI15M", datetime(2026, 11, 6, 12, 0, tzinfo=UTC))
    assert quiet["event_kind"] == "none" and not quiet["event_within_15"]
    # The oil releases do not flag a metals series.
    assert event_feature("KXGOLD15M", datetime(2026, 11, 11, 15, 30,
                                              tzinfo=UTC))["event_kind"] == "none"


def test_sources_are_never_pooled_together():
    base = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
    fwd, rep = [], []
    for i in range(35):
        close = base + timedelta(minutes=15 * i)
        fwd += window("KXWTI15M", close, 1, trade_offset=5, pnl=0.10)
        rep += window("KXWTI15M", close, 1, trade_offset=5, pnl=-0.10)
    report = build_report(fwd, rep)
    five = next(r for r in report["views"]["all"]["features"]["minute"]
                if r["bucket"] == "5")
    pooled = five["cells"]["POOLED"]
    assert pooled["forward"]["cents"] == 10.0 and pooled["replay"]["cents"] == -10.0
    assert "data_so_far" in report and report["label"].startswith("in-sample")
