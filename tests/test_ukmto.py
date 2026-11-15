"""UKMTO incident layer (Kevin's Hormuz build, 2026-11-14): the incident
feed behind UKMTO's own Recent Incidents map, served by the Royal Navy's
Sitecore host (sccd.royalnavy.mod.uk/api/ukmto/all, no key). The pull
keeps every incident; the reader keeps the Hormuz-relevant ones (place
'Strait of Hormuz' or coordinates inside the region box) and serves the
last good pull fail-soft, with its as-of stated -- a missing cache reads
as no panel, never an error and never an invented incident.
"""
import json
from datetime import UTC, datetime

import pytest

from tradehub.geo import ukmto

# Shaped like the live API rows (Nov 2026): one Hormuz attack, one Gulf of
# Oman advisory inside the region box, one Bab el Mandeb attack outside it,
# and one malformed row.
API_ROWS = [
    {"incidentIssuer": "UKMTO", "incidentNumber": 204, "sitecoreId": "aaa",
     "utcDateCreated": "2026-11-12T09:00:00Z", "utcDateOfIncident": "2026-11-11T18:00:00Z",
     "incidentTypeName": "Attack", "locationLatitude": 25.9, "locationLongitude": 55.9,
     "place": "Arabian Gulf", "vesselName": "withheld", "vesselType": "Tanker ",
     "otherDetails": "UKMTO has received a time-late report of an incident 14NM northwest "
                     "of Ra's al Khaymah, UAE.\r\n\r\nA tanker was struck by an unknown projectile."},
    {"incidentIssuer": "UKMTO", "incidentNumber": 198, "sitecoreId": "bbb",
     "utcDateCreated": "2026-11-07T12:00:00Z", "utcDateOfIncident": "2026-11-07T06:30:00Z",
     "incidentTypeName": "Advisory", "locationLatitude": 24.6, "locationLongitude": 58.6,
     "place": "Gulf of Oman", "vesselName": "HUDA", "vesselType": "Bulk Carrier",
     "otherDetails": "UKMTO has received a report of an incident involving a vessel and "
                     "military forces 18NM east of Khor Fakkan, UAE."},
    {"incidentIssuer": "UKMTO", "incidentNumber": 151, "sitecoreId": "ccc",
     "utcDateCreated": "2026-10-04T08:00:00Z", "utcDateOfIncident": "2026-10-04T05:00:00Z",
     "incidentTypeName": "Attack", "locationLatitude": 12.6, "locationLongitude": 43.4,
     "place": "Bab el Mandeb", "vesselName": "withheld", "vesselType": "Tanker",
     "otherDetails": "Explosions close to the vessel 60NM south of Al Mukha."},
    {"incidentIssuer": "UKMTO", "incidentNumber": None, "utcDateOfIncident": "not a date"},
]


def test_parse_normalizes_and_skips_malformed_rows():
    rows = ukmto.parse_incidents(API_ROWS)
    assert len(rows) == 3
    first = rows[0]
    assert first["ref"] == "UKMTO 204-26"
    assert first["date"] == "2026-11-11" and first["type"] == "Attack"
    assert first["place"] == "Arabian Gulf" and first["vessel_type"] == "Tanker"
    assert "\r" not in first["description"] and "14NM northwest" in first["description"]
    assert first["url"] == ukmto.SOURCE_URL


def test_parse_rejects_a_non_list_body():
    assert ukmto.parse_incidents({"error": "nope"}) == []
    assert ukmto.parse_incidents(None) == []


def test_fetch_retries_then_raises_ukmto_error():
    calls = {"n": 0}

    def flaky(_url):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("boom")
        return API_ROWS

    rows = ukmto.fetch_incidents(get=flaky, sleep=lambda s: None)
    assert len(rows) == 3

    def dead(_url):
        raise OSError("boom")

    with pytest.raises(ukmto.UkmtoError):
        ukmto.fetch_incidents(get=dead, sleep=lambda s: None)


def test_fetch_empty_list_is_a_valid_empty_window():
    # An empty rolling window is a real answer: the fetch returns it
    # instead of retrying into a failure that would keep stale incidents.
    assert ukmto.fetch_incidents(get=lambda _url: [], sleep=lambda s: None) == []


def test_fetch_non_list_body_raises_after_retries():
    calls = {"n": 0}

    def wrong_shape(_url):
        calls["n"] += 1
        return {"error": "nope"}

    with pytest.raises(ukmto.UkmtoError):
        ukmto.fetch_incidents(get=wrong_shape, sleep=lambda s: None)
    assert calls["n"] == 3


def test_fetch_malformed_only_rows_raise():
    # A non-empty list whose rows all fail parsing is a shape failure,
    # not an empty window: it must not clear the cache.
    junk = [{"incidentIssuer": "UKMTO", "incidentNumber": None,
             "utcDateOfIncident": "not a date"}]
    with pytest.raises(ukmto.UkmtoError):
        ukmto.fetch_incidents(get=lambda _url: junk, sleep=lambda s: None)


def test_pull_writes_an_empty_window_and_clears_stale_incidents(tmp_path, monkeypatch):
    from tradehub.scripts import ukmto_pull

    path = _write_cache(tmp_path, monkeypatch,
                        {"pulled_at": "2026-11-14T12:23:00+00:00",
                         "incidents": ukmto.parse_incidents(API_ROWS)})
    assert ukmto.load_incidents("hormuz") is not None  # the stale panel is up
    monkeypatch.setattr(ukmto, "fetch_incidents", lambda: [])
    ukmto_pull.main()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["incidents"] == [] and payload["pulled_at"]
    assert ukmto.load_incidents("hormuz") is None  # and now it is cleared
    # The atomic write leaves no temp file behind.
    assert not (tmp_path / "ukmto.json.tmp").exists()


def _write_cache(tmp_path, monkeypatch, payload):
    path = tmp_path / "ukmto.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("GEO_UKMTO", str(path))
    return path


def test_load_keeps_only_hormuz_relevant_newest_first(tmp_path, monkeypatch):
    _write_cache(tmp_path, monkeypatch,
                 {"pulled_at": "2026-11-14T12:23:00+00:00",
                  "incidents": ukmto.parse_incidents(API_ROWS)})
    out = ukmto.load_incidents("hormuz", now=datetime(2026, 11, 14, 22, 0, tzinfo=UTC))
    assert out["source"] == "UKMTO" and out["pulled_at"] == "2026-11-14T12:23:00+00:00"
    # Bab el Mandeb is outside the region box and not the strait: excluded.
    assert [i["ref"] for i in out["incidents"]] == ["UKMTO 204-26", "UKMTO 198-26"]
    assert out["as_of"] == "2026-11-11" and out["count"] == 2


def test_load_missing_corrupt_and_unmapped_read_as_no_panel(tmp_path, monkeypatch):
    monkeypatch.setenv("GEO_UKMTO", str(tmp_path / "absent.json"))
    assert ukmto.load_incidents("hormuz") is None
    path = tmp_path / "ukmto.json"
    path.write_text("{not json")
    monkeypatch.setenv("GEO_UKMTO", str(path))
    assert ukmto.load_incidents("hormuz") is None
    _write_cache(tmp_path, monkeypatch,
                 {"pulled_at": "2026-11-14T12:23:00+00:00",
                  "incidents": ukmto.parse_incidents(API_ROWS)})
    assert ukmto.load_incidents("atlantis") is None


def test_region_view_carries_incidents_and_survives_a_missing_cache(tmp_path, monkeypatch):
    from tests.test_geo import _Fake
    from tradehub.geo.read import region_view

    monkeypatch.setenv("GEO_UKMTO", str(tmp_path / "absent.json"))
    view = region_view(_Fake([]), "hormuz")
    assert view["incidents"] is None  # panel absent, page unaffected

    _write_cache(tmp_path, monkeypatch,
                 {"pulled_at": "2026-11-14T12:23:00+00:00",
                  "incidents": ukmto.parse_incidents(API_ROWS)})
    view = region_view(_Fake([]), "hormuz")
    assert view["incidents"]["count"] == 2
    assert view["incidents"]["incidents"][0]["ref"] == "UKMTO 204-26"
