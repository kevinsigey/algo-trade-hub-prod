"""Exhibit A: the fact sheet rendered as the debate's fixed factual core, and
the peer state frozen at render time (spec section 6: grading joins exactly
what the verdict saw)."""
from tradehub.valuation import exhibit


def _row(**over):
    row = {
        "id": 41, "ticker": "AMGN", "tier": "watch", "status": "banded",
        "price": 460.42, "price_as_of": "2026-11-06",
        "peer_group": "biotechnology", "peer_multiple": 16.49,
        "peer_count": 7, "peer_basis": "industry_group",
        "anchor": {"metric": "eps_adjusted", "period": "FY2026",
                   "period_key": "FY2026", "low": 18.34, "high": 19.28,
                   "mid": 18.81, "point_guide": False, "consensus": 18.9,
                   "recorded_at": "2026-11-05T12:00:00+00:00",
                   "accession": "0000318154-26-000153"},
        "bands": {"bear": 272.18, "base": 310.17, "bull": 317.92},
        "implied_eps": 27.92, "implied_revenue": None, "band_basis": "eps",
        "gap_range_widths": 9.69, "guidance_percentile": None,
        "baseline_verdict": "short_zone_strong", "stale": False,
        "falsifier": "Falsified if AMGN guides FY2026 EPS below 18.34 ...",
        "directions": {"eps_adjusted": {"period": "FY2026", "mid": 18.81,
                                        "direction": "raised",
                                        "recorded_at": "2026-11-05T12:00:00+00:00"}},
        "fundamentals": {
            "eps_diluted": {"value": 10.2, "as_of": "2025-12-31"},
            "cash": {"value": 5.1e9, "as_of": "2026-09-30"},
            "missing": ["debt_current"]},
        "computed_at": "2026-11-08T04:00:00+00:00",
    }
    row.update(over)
    return row


def test_exhibit_carries_the_whole_sheet():
    ex = exhibit.exhibit_a(_row())
    assert ex["ticker"] == "AMGN" and ex["fact_sheet_id"] == 41
    assert ex["bands"] == {"bear": 272.18, "base": 310.17, "bull": 317.92}
    assert ex["baseline_verdict"] == "short_zone_strong"
    assert ex["anchor"]["low"] == 18.34 and ex["anchor"]["high"] == 19.28
    assert ex["peer"]["group"] == "biotechnology"
    assert ex["peer"]["multiple"] == 16.49 and ex["peer"]["count"] == 7
    assert ex["fundamentals"]["cash"] == {"value": 5.1e9, "as_of": "2026-09-30"}
    assert ex["falsifier"].startswith("Falsified if AMGN")


def test_exhibit_markdown_states_price_bands_guide_and_falsifier():
    md = exhibit.render_markdown(exhibit.exhibit_a(_row()))
    assert "AMGN" in md and "460.42" in md
    assert "272.18" in md and "310.17" in md and "317.92" in md
    assert "18.34" in md and "19.28" in md      # the guide itself
    assert "short_zone_strong" in md            # the band rule's own verdict
    assert "Falsified if AMGN" in md
    assert "raised" in md                       # guide direction


def test_freeze_peer_states_records_each_members_price():
    row = _row()
    prices = {t: (100.0 + i, "2026-11-06") for i, t in enumerate(
        ["ABBV", "AMGN", "BIIB", "GILD", "INCY", "MRNA", "REGN", "VRTX"])}
    prices["GILD"] = (168.57, "2026-11-06")
    frozen = exhibit.freeze_peer_states(
        row, prices_fn=lambda members: {m: prices[m] for m in members
                                        if m in prices})
    assert frozen["group"] == "biotechnology"
    assert frozen["multiple"] == 16.49
    by_ticker = {m["ticker"]: m for m in frozen["members"]}
    assert by_ticker["GILD"]["price"] == 168.57
    assert len(by_ticker) == 8
    assert all(m["price"] is not None for m in frozen["members"])


def test_freeze_peer_states_records_absence_instead_of_inventing():
    frozen = exhibit.freeze_peer_states(
        _row(), prices_fn=lambda members: {"AMGN": (460.42, "2026-11-06")})
    by_ticker = {m["ticker"]: m for m in frozen["members"]}
    assert by_ticker["AMGN"]["price"] == 460.42
    assert by_ticker["GILD"]["price"] is None  # absent is data, never a guess
