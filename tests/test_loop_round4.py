"""Loop Round 4: saved-run results viewable from the record, the debate
queue + named exclusions surfaced in aggregate, and the print-classification
write path (forward_file_classifications).

Item 1: the saved-run endpoint records the run's ROWS (not just counts), so
the record itself can be viewed without re-executing.
Item 2: generation persists the named exclusions per snapshot; the queue
endpoint serves pending counts by class + the exclusions, stamped.
Item 3: POST /api/v1/forward-file/classifications under machine-key
discipline (bearer key, classifications:write scope); the store satisfies
the readers Spec C (band_crossing.t1_classification) and Spec D / Batch 2
(candidates.print_classification) already call -- no consumer changes.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.valuation import band_crossing, candidates, classifications
from tests.test_valuation_verdicts import FakeClient

NOW = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)


def _client(c: FakeClient) -> TestClient:
    main.app.dependency_overrides[admin.require_admin] = lambda: {"role": "admin"}
    main.app.dependency_overrides[get_supabase] = lambda: c
    return TestClient(main.app)


# -- Item 1: recorded runs keep their rows -----------------------------------


def test_saved_run_records_its_rows(monkeypatch):
    c = FakeClient()
    c.tables["screens"] = [{
        "id": 6, "name": "Buffett quality (classic)",
        "spec": {"name": "buffett_quality_classic",
                 "universe": {"type": "list", "tickers": ["AAA", "BBB"]}},
        "last_run": None, "membership": None, "membership_events": None,
    }]
    table = pd.DataFrame([
        {"ticker": "AAA", "roe": 21.5, "score": 88.0},
        {"ticker": "BBB", "roe": 17.0, "score": 71.0},
    ])
    footer = {"run_at": "2026-11-10T06:00:00Z", "survivors": 2,
              "survivor_issuers": 2, "survivor_tickers": ["AAA", "BBB"],
              "displayed": 2, "display_limit": None, "data_as_of": "2026-11-10",
              "columns": {"roe": {"fn": "roe", "source": "yfinance.info"}}}

    class _Result:
        pass

    result = _Result()
    result.table, result.footer = table, footer
    monkeypatch.setattr("tradehub.screening.run_spec", lambda spec: result)

    resp = _client(c).post("/api/screening/screens/6/run")
    assert resp.status_code == 200, resp.text
    stored = c.tables["screens"][0]["last_run"]
    assert stored["rows"] == [{"ticker": "AAA", "roe": 21.5, "score": 88.0},
                              {"ticker": "BBB", "roe": 17.0, "score": 71.0}]
    assert stored["columns"] == ["ticker", "roe", "score"]
    assert stored["survivors"] == ["AAA", "BBB"]
    # The recorded view (single-screen read) carries the rows back out.
    view = _client(c).get("/api/screening/screens/6").json()
    assert view["last_run"]["rows"][0]["ticker"] == "AAA"


# -- Item 2: exclusions persisted + queue served in aggregate -----------------


def _snapshot_seed(c: FakeClient) -> None:
    c.tables["valuation_snapshots"] = [{
        "id": 3, "computed_at": "2026-11-10T00:39:00Z",
        "completed_at": "2026-11-10T00:39:30Z", "sheet_count": 3,
        "banded_count": 2, "source": "nightly"}]


def test_generation_persists_named_exclusions_once():
    from tests.test_debate_candidates import _seeded

    c = _seeded()
    candidates.generate_candidates(c, now=NOW)
    rows = c.tables.get("debate_candidate_exclusions") or []
    by_ticker = {r["ticker"]: r for r in rows}
    assert set(by_ticker) == {"MSFT", "XYZ", "NEUT"}
    assert by_ticker["MSFT"]["reason"] == "no fact sheet in snapshot #3"
    assert by_ticker["XYZ"]["snapshot_id"] == 3
    # Regenerating the same snapshot upserts -- never duplicates.
    candidates.generate_candidates(c, now=NOW)
    assert len(c.tables["debate_candidate_exclusions"]) == 3


def test_queue_endpoint_serves_counts_exclusions_and_stamp():
    c = FakeClient()
    _snapshot_seed(c)
    c.tables["debate_candidates"] = [
        {"id": 1, "ticker": "HOT", "snapshot_id": 3,
         "candidate_class": "zone", "priority": 20, "state": "pending",
         "sources": {"zone": "short_zone_strong"}, "detail": None,
         "verdict_id": None, "computed_at": "2026-11-10T04:47:00Z"},
        {"id": 2, "ticker": "OLD", "snapshot_id": 3,
         "candidate_class": "entrant", "priority": 30, "state": "rendered",
         "sources": {}, "detail": None, "verdict_id": 9,
         "computed_at": "2026-11-10T04:47:00Z"},
    ]
    c.tables["debate_candidate_exclusions"] = [
        {"id": 1, "ticker": "MSFT", "snapshot_id": 3,
         "reason": "no fact sheet in snapshot #3",
         "computed_at": "2026-11-10T04:47:00Z"},
    ]
    body = _client(c).get("/api/debate-candidates").json()
    assert body["snapshot"]["id"] == 3
    assert body["pending_by_class"] == {"conjunction": 0, "entrant": 0, "zone": 1}
    assert body["excluded"] == [
        {"ticker": "MSFT", "reason": "no fact sheet in snapshot #3",
         "computed_at": "2026-11-10T04:47:00Z"}]
    assert body["generated_at"] == "2026-11-10T04:47:00Z"


# -- Item 3: the classification store + machine write endpoint -----------------

URL = "/api/v1/forward-file/classifications"


def _key(c: FakeClient, scopes=("classifications:write",)):
    _row, plaintext = machine_keys.create_key(c, "thesis prints", list(scopes))
    return {"Authorization": f"Bearer {plaintext}"}


def test_classification_write_read_back_through_spec_c_provider():
    c = FakeClient()
    headers = _key(c)
    resp = _client(c).post(URL, headers=headers, json={
        "ticker": "ceg", "classification": "improved", "as_of": "2026-11-09",
        "source": "print log", "note": "raised FY guide"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["recorded"]["ticker"] == "CEG"
    assert body["recorded"]["recorded_by"] == "thesis prints"
    assert body["current"] == "improved"
    # The exact readers Spec C and the conjunction leg already call:
    assert band_crossing.t1_classification(c, "CEG") == "improved"
    assert candidates.print_classification(c, "CEG") == {
        "classification": "improved", "as_of": "2026-11-09"}


def test_classification_write_auth_and_shape():
    c = FakeClient()
    payload = {"ticker": "CEG", "classification": "improved",
               "as_of": "2026-11-09"}
    assert _client(c).post(URL, json=payload).status_code == 401
    read_only = _key(c, scopes=("portfolio:read",))
    assert _client(c).post(URL, headers=read_only,
                           json=payload).status_code == 403
    headers = _key(c)
    # The thesis log's own vocabulary is NOT a consumer value: refused loudly,
    # never stored unreadable (map no_surprise -> intact at the source).
    bad = _client(c).post(URL, headers=headers, json={
        **payload, "classification": "no_surprise"})
    assert bad.status_code == 422
    assert "intact" in bad.json()["detail"]
    assert _client(c).post(URL, headers=headers, json={
        **payload, "as_of": "not a date"}).status_code == 422
    assert _client(c).post(URL, headers=headers, json={
        **payload, "ticker": "WAY TOO LONG TICKER!"}).status_code == 422
    assert not (c.tables.get("forward_file_classifications") or [])


def test_classification_latest_row_by_as_of_wins():
    c = FakeClient()
    headers = _key(c)
    client = _client(c)
    client.post(URL, headers=headers, json={
        "ticker": "KKR", "classification": "deteriorated",
        "as_of": "2026-11-02"})
    client.post(URL, headers=headers, json={
        "ticker": "KKR", "classification": "improved", "as_of": "2026-11-09"})
    assert band_crossing.t1_classification(c, "KKR") == "improved"


def test_classification_module_validates_and_stamps():
    c = FakeClient()
    with pytest.raises(ValueError):
        classifications.record_classification(
            c, ticker="CEG", classification="fork-A", as_of="2026-11-09")
    row = classifications.record_classification(
        c, ticker=" oxy ", classification="intact", as_of="2026-11-09",
        source="print log", recorded_by="test", now=NOW)
    assert row["ticker"] == "OXY"
    assert row["recorded_at"] == "2026-11-10T06:00:00+00:00"
    assert band_crossing.t1_classification(c, "OXY") == "intact"
