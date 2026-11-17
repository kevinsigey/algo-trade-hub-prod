"""Thesis tracker PR 3: the forecast-card store + write/read endpoints.

The card contract (design docs/superpowers/specs/
2026-11-16-thesis-tracker-design.md): one card per covered name per
print, frozen BEFORE the release -- the write path rejects any card at
or after print_at, cards are never edited (a correction is a new
pre-print card superseding the old), and the graded card for a print is
the latest pre-print one. The two signals (whisper, money flow) are
stored as separate fields; nothing here combines them.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub.api import admin, machine_keys, main
from tradehub.api.dependencies import get_supabase
from tradehub.tracker import cards
from tests.test_valuation_verdicts import FakeClient

PRINT = "2026-11-20T21:00:00Z"          # a Friday after-hours print
BEFORE = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
AT = datetime(2026, 11, 20, 21, 0, tzinfo=timezone.utc)
AFTER = datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc)


def _seeded() -> FakeClient:
    c = FakeClient()
    c.tables["theses"] = [
        {"id": 1, "slug": "event-lab", "title": "Event lab (T1 rebuilt)",
         "sleeve": "event_lab", "status": "live", "kill_lines": [],
         "spec_ref": None},
        {"id": 2, "slug": "core", "title": "Core beta (T3+T8 merged)",
         "sleeve": "core", "status": "live", "kill_lines": [],
         "spec_ref": None},
    ]
    return c


def _card(c: FakeClient, **over):
    kw = {"ticker": "NVDA", "thesis_slug": "event-lab", "print_at": PRINT,
          "whisper_esp": 0.04, "whisper_sign": "positive",
          "money_flow_direction": "inflow",
          "money_flow_evidence": [{"text": "hyperscaler capex raised",
                                   "source": "https://example.com/print"}],
          "guide_position": "guide below the priced trajectory",
          "predicted_direction": "down",
          "opposing_case_ref": "research/nvda.md#opposing-case",
          "classification": "deteriorated", "now": BEFORE}
    kw.update(over)
    return cards.create_card(c, **kw)


# -- the store ---------------------------------------------------------------


def test_create_card_stores_the_full_contract():
    c = _seeded()
    row = _card(c)
    assert row["ticker"] == "NVDA"
    assert row["thesis_id"] == 1
    assert row["whisper_sign"] == "positive"
    assert row["money_flow_direction"] == "inflow"
    assert row["classification"] == "deteriorated"
    assert c.tables["forecast_cards"][0]["print_at"] == \
        "2026-11-20T21:00:00+00:00"  # the store normalizes to an instant


def test_card_at_or_after_the_release_is_rejected():
    c = _seeded()
    with pytest.raises(ValueError, match="at or after the release"):
        _card(c, now=AT)
    with pytest.raises(ValueError, match="at or after the release"):
        _card(c, now=AFTER)
    assert c.tables.get("forecast_cards", []) == []


def test_unknown_thesis_slug_is_rejected():
    c = _seeded()
    with pytest.raises(ValueError, match="no thesis with slug"):
        _card(c, thesis_slug="nope")


def test_bad_enum_values_are_named_and_rejected():
    c = _seeded()
    with pytest.raises(ValueError, match="whisper_sign"):
        _card(c, whisper_sign="huge")
    with pytest.raises(ValueError, match="money_flow_direction"):
        _card(c, money_flow_direction="sideways")
    with pytest.raises(ValueError, match="predicted_direction"):
        _card(c, predicted_direction="moon")
    with pytest.raises(ValueError, match="classification"):
        _card(c, classification="no_surprise")


def test_money_flow_direction_requires_named_evidence():
    c = _seeded()
    with pytest.raises(ValueError, match="evidence"):
        _card(c, money_flow_evidence=[])
    with pytest.raises(ValueError, match="evidence"):
        _card(c, money_flow_evidence=[{"text": "vibes"}])


def test_superseding_card_must_target_the_same_print():
    c = _seeded()
    first = _card(c)
    second = _card(c, supersedes_id=first["id"],
                   predicted_direction="up")
    assert second["supersedes_id"] == first["id"]
    with pytest.raises(ValueError, match="same ticker and print"):
        _card(c, supersedes_id=first["id"], ticker="AMD")
    with pytest.raises(ValueError, match="no card with id"):
        _card(c, supersedes_id=999)


def test_graded_card_is_the_latest_pre_print_card():
    c = _seeded()
    first = _card(c, now=datetime(2026, 11, 19, 12, 0,
                                  tzinfo=timezone.utc))
    second = _card(c, supersedes_id=first["id"], now=BEFORE,
                   predicted_direction="up")
    graded = cards.graded_card(c, "NVDA", PRINT)
    assert graded["id"] == second["id"]
    # A row stamped after the print (written by no route; seeded here to
    # prove the reader's guard) is never the graded card.
    c.tables["forecast_cards"].append(
        {"id": 99, "ticker": "NVDA", "thesis_id": 1, "print_at": PRINT,
         "frozen_at": "2026-11-20T21:05:00+00:00"})
    assert cards.graded_card(c, "NVDA", PRINT)["id"] == second["id"]
    assert cards.graded_card(c, "NVDA", "2027-01-01T00:00:00Z") is None


def test_list_cards_marks_superseded():
    c = _seeded()
    first = _card(c, now=datetime(2026, 11, 19, 12, 0,
                                  tzinfo=timezone.utc))
    _card(c, supersedes_id=first["id"], now=BEFORE)
    rows = cards.list_cards(c)
    by_id = {r["id"]: r for r in rows}
    assert by_id[first["id"]]["superseded"] is True
    assert by_id[2]["superseded"] is False


# -- the endpoints -------------------------------------------------------------

WRITE_URL = "/api/v1/thesis/forecast-cards"
READ_URL = "/api/thesis/cards"


def _client(c: FakeClient) -> TestClient:
    main.app.dependency_overrides[admin.require_admin] = lambda: {"role": "admin"}
    main.app.dependency_overrides[get_supabase] = lambda: c
    return TestClient(main.app)


def _key(c: FakeClient, scopes=("tracker:write",)):
    _row, plaintext = machine_keys.create_key(c, "tracker test", list(scopes))
    return {"Authorization": f"Bearer {plaintext}"}


def _payload(**over):
    body = {"ticker": "NVDA", "thesis_slug": "event-lab",
            "print_at": "2030-01-01T21:00:00Z",
            "whisper_sign": "positive",
            "money_flow_direction": "inflow",
            "money_flow_evidence": [{"text": "capex raised",
                                     "source": "https://example.com"}],
            "predicted_direction": "down",
            "classification": "deteriorated"}
    body.update(over)
    return body


def test_write_endpoint_records_and_reads_back():
    c = _seeded()
    resp = _client(c).post(WRITE_URL, headers=_key(c), json=_payload())
    assert resp.status_code == 201, resp.text
    recorded = resp.json()["recorded"]
    assert recorded["ticker"] == "NVDA"
    assert recorded["thesis_id"] == 1
    view = _client(c).get(READ_URL).json()
    assert [r["ticker"] for r in view["cards"]] == ["NVDA"]
    assert view["cards"][0]["superseded"] is False


def test_read_endpoint_rejects_a_signed_out_request():
    """Kevin's call (Nov 16, relayed on #524 as 6939739790): the cards
    read is admin-only too -- the cards carry money_flow_evidence and
    guide_position. This test overrides ONLY the supabase dependency;
    require_admin runs for real and a request with no Bearer <redacted>
    gets its 401. (The _client helper's override covers the happy
    path above; the machine-key write route is untouched.)"""
    c = _seeded()
    # _client() leaves its require_admin override installed; remove it
    # explicitly or this test would inherit the pass it exists to deny.
    main.app.dependency_overrides.pop(admin.require_admin, None)
    main.app.dependency_overrides[get_supabase] = lambda: c
    try:
        resp = TestClient(main.app).get(READ_URL)
    finally:
        main.app.dependency_overrides.clear()
    assert resp.status_code == 401, resp.text
    assert "cards" not in resp.json()


def test_write_endpoint_needs_the_tracker_scope():
    c = _seeded()
    resp = _client(c).post(WRITE_URL, headers=_key(c, ("portfolio:read",)),
                           json=_payload())
    assert resp.status_code == 403


def test_write_endpoint_rejects_a_card_for_a_past_print():
    c = _seeded()
    resp = _client(c).post(WRITE_URL, headers=_key(c),
                           json=_payload(print_at="2020-01-01T21:00:00Z"))
    assert resp.status_code == 422
    assert "at or after the release" in resp.json()["detail"]


def test_write_endpoint_rejects_unknown_fields():
    c = _seeded()
    resp = _client(c).post(WRITE_URL, headers=_key(c),
                           json=_payload(combined_score=0.9))
    assert resp.status_code == 422
