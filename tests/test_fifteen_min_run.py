"""The dedicated 15-minute runner (Kevin, 2026-11-04): every window gets
a prediction. The script narrows the journal's own runner to the
fifteen_min roster; this test proves a pass freezes the live window's
rows into the journal tables through that path (and that a second pass
dedupes instead of doubling them).
"""
from datetime import timedelta

from journal_fakes import FakeJournalDB
from tests.test_fifteen_min import T0, _Live, _market, _tape

from tradehub.journal.forecasters.fifteen_min import FifteenMinInputs, build_fifteen_min
from tradehub.scripts.fifteen_min_run import run


def test_a_pass_freezes_the_live_window_and_a_second_pass_dedupes():
    now = T0 + timedelta(minutes=5)
    live = _Live([_market(T0 + timedelta(minutes=15))])
    built = build_fifteen_min(live, inputs=FifteenMinInputs(candles_fn=lambda c, s, e: _tape()))
    db = FakeJournalDB(lambda: now)
    summary = run(db, built, now)
    assert summary["oil_wti_15m"]["frozen"] == 1
    rows = [r for r in db.tables["journal_forecasts"] if r["forecaster"] == "oil_wti_15m"]
    assert len(rows) == 1 and rows[0]["forecaster_version"] == "wti-15m-v2"
    again = run(db, built, now)
    assert again["oil_wti_15m"]["frozen"] == 0
    assert len([r for r in db.tables["journal_forecasts"] if r["forecaster"] == "oil_wti_15m"]) == 1
