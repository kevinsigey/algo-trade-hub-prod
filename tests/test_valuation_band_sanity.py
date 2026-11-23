"""Debate fix 3 (#580): band sanity. A price implausibly far outside its
guidance band (in band widths) marks the fact sheet band_suspect; a
suspect sheet does not debate and renders no verdict. N =
engine.BAND_SUSPECT_WIDTHS, picked from the post-step-10 distribution
(see the constant's comment)."""
from datetime import date, datetime, timezone

from tradehub.valuation import engine, store, verdicts
from tests.test_valuation_verdicts import FakeClient, _sheet_row

NOW = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc)


def _records():
    return [{"ticker": "ACME", "metric": "eps_adjusted", "period": "FY2027",
             "low": 4.0, "high": 6.0, "unit": "usd_per_share",
             "consensus": 4.2, "consensus_period": "FY2027",
             "created_at": "2026-11-01T00:00:00+00:00", "accession": "0001"}]


def _sheet(price, **kw):
    kw.setdefault("peer_median_fwd_eps", 4.0)
    kw.setdefault("peer_count", 6)
    kw.setdefault("peer_basis", "industry_group")
    kw.setdefault("guided_peers", [])
    kw.setdefault("fundamentals", {})
    kw.setdefault("price_date", date(2026, 11, 18))
    return engine.build_fact_sheet(
        ticker="ACME", records=_records(), price=price,
        peer_multiple=20.0, now=datetime(2026, 11, 19, tzinfo=timezone.utc),
        **kw)


def test_distance_widths_math():
    bands = {"bear": 72.0, "base": 100.0, "bull": 120.0}  # width 48
    assert engine.band_distance_widths(100.0, bands) == 0.0
    assert engine.band_distance_widths(120.0, bands) == 0.0
    assert engine.band_distance_widths(168.0, bands) == 1.0
    assert engine.band_distance_widths(24.0, bands) == -1.0
    assert engine.band_distance_widths(None, bands) is None
    assert engine.band_distance_widths(100.0, None) is None
    assert engine.band_distance_widths(
        100.0, {"bear": 100.0, "base": 100.0, "bull": 100.0}) is None


def test_sheet_inside_its_band_is_not_suspect():
    sheet = _sheet(80.0)  # bands 72 / 100 / 120
    assert sheet["band_widths_outside"] == 0.0
    assert sheet["band_suspect"] is False


def test_sheet_at_the_widest_live_distance_is_not_suspect():
    # PLTR sat 42.1 widths above its band in the 2026-11-23 snapshot --
    # extreme but legitimate; the guard is for broken bands, not for
    # high-multiple names.
    sheet = _sheet(120.0 + 42.0 * 48.0)
    assert sheet["band_widths_outside"] == 42.0
    assert sheet["band_suspect"] is False


def test_sheet_hundreds_of_widths_out_is_suspect():
    # The 2026-11-19 broken-band signature: ~292 widths out.
    sheet = _sheet(120.0 + 292.0 * 48.0)
    assert sheet["band_widths_outside"] == 292.0
    assert sheet["band_suspect"] is True


def test_store_round_trips_the_band_fields_via_inputs():
    """No new columns: insert_sheet folds band_suspect /
    band_widths_outside into the stored inputs jsonb, and the read
    helpers lift them back to the sheet's top level."""
    client = FakeClient()
    sheet = _sheet(120.0 + 292.0 * 48.0)
    sheet["inputs"] = {"guidance_records": []}
    store.insert_sheet(client, sheet)
    [row] = client.tables["valuation_fact_sheets"]
    assert row["inputs"]["band_suspect"] is True
    assert row["inputs"]["band_widths_outside"] == 292.0
    [served] = store.latest_sheets(client)
    assert served["band_suspect"] is True
    assert served["band_widths_outside"] == 292.0


def test_pre_fix_rows_lift_to_not_suspect():
    client = FakeClient()
    client.tables["valuation_fact_sheets"] = [_sheet_row()]
    [served] = store.latest_sheets(client)
    assert not served.get("band_suspect")


def test_suspect_sheet_does_not_render_a_verdict():
    client = FakeClient()
    client.tables["valuation_fact_sheets"] = [
        _sheet_row(band_suspect=True, band_widths_outside=292.0)]
    out = verdicts.render_verdict(client, None, "AMGN",
                                  trigger="crossing", now=NOW)
    assert out["status"] == "band_suspect"
    assert "292.0 band widths" in out["reason"]
    assert client.tables.get("valuation_verdicts", []) == []
