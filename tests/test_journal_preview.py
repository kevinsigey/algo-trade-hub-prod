from datetime import UTC, datetime
from unittest.mock import MagicMock

from test_journal_cpi_fomc import NOW, FakeLive, _cpi, _nowcast
from tradehub.journal import preview
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.preview import PREVIEW_LEAD, run_previews

PARAMS = {"train_months": 24.0, "use_bias": 0.0}


def _cpi_fc(live, lead):
    return CpiForecaster("KXCPI", live, lambda t: None, nowcast_fn=_nowcast, params=PARAMS, lead=lead)


def test_a_month_out_market_is_a_preview_target_but_not_a_frozen_one():
    live = FakeLive([_cpi("KXCPI", 0.3, close="2026-10-11T12:25:00Z")])
    assert _cpi_fc(live, lead=PREVIEW_LEAD).targets(NOW) != []
    assert CpiForecaster("KXCPI", live, lambda t: None, nowcast_fn=_nowcast, params=PARAMS).targets(NOW) == []


def test_preview_rows_carry_the_model_and_market_probability(monkeypatch):
    live = FakeLive([_cpi("KXCPI", 0.3, close="2026-10-11T12:25:00Z")])
    monkeypatch.setattr(preview, "PayrollsForecaster", lambda *a, **k: MagicMock(targets=lambda now: []))
    monkeypatch.setattr(preview, "CpiForecaster",
                        lambda series, live, fm, **k: _cpi_fc(live, k["lead"]) if series == "KXCPI"
                        else MagicMock(targets=lambda now: []))
    rows = preview.build_previews(NOW, live=live, labor=object())
    assert len(rows) == 1 and rows[0]["forecaster"] == "cpi_nowcast"
    assert 0 < rows[0]["probability"] < 1 and rows[0]["market_prob"] == 0.32
    assert rows[0]["close_at"].startswith("2026-10-11")


def test_a_failing_source_does_not_hide_the_others(monkeypatch):
    class Boom:
        name = "boom"
        def targets(self, now): raise RuntimeError("fred down")
    ok = MagicMock(targets=lambda now: [])
    monkeypatch.setattr(preview, "CpiForecaster", lambda *a, **k: Boom())
    monkeypatch.setattr(preview, "PayrollsForecaster", lambda *a, **k: ok)
    assert preview.build_previews(datetime(2026, 9, 1, tzinfo=UTC), live=object(), labor=object()) == []


def test_run_previews_never_touches_the_scored_tables(monkeypatch):
    monkeypatch.setattr(preview, "build_previews", lambda now, **k: [{"target": "t"}])
    supa = MagicMock()
    assert run_previews(supa, NOW) == {"previews": 1}
    assert {c.args[0] for c in supa.table.call_args_list} == {"journal_previews"}


def test_expiry_is_by_close_time_even_when_nothing_was_produced(monkeypatch):
    monkeypatch.setattr(preview, "build_previews", lambda now, **k: [])
    supa = MagicMock()
    run_previews(supa, NOW)
    supa.table.return_value.delete.return_value.lte.assert_called_once()
    assert supa.table.return_value.delete.return_value.lte.call_args.args[0] == "close_at"
    supa.table.return_value.upsert.assert_not_called()


def test_a_market_inside_the_freeze_window_is_not_previewed(monkeypatch):
    live = FakeLive([_cpi("KXCPI", 0.3, close="2026-09-11T20:00:00Z")])  # 8h out: the journal locks it
    monkeypatch.setattr(preview, "PayrollsForecaster", lambda *a, **k: MagicMock(targets=lambda now: []))
    monkeypatch.setattr(preview, "CpiForecaster",
                        lambda series, live, fm, **k: _cpi_fc(live, k["lead"]) if series == "KXCPI"
                        else MagicMock(targets=lambda now: []))
    assert preview.build_previews(NOW, live=live, labor=object()) == []
