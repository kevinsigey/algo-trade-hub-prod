"""The forked debate (spec section 4): bulls and bears argue over Exhibit A
only; the structurer turns the argument into a typed decision packet whose
prices ARE the band prices — code validates them against the sheet, and a
mismatch voids the verdict rather than letting an invented number stand."""
import pytest

from tradehub.valuation import debate_fork, exhibit


def _ex():
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
        "directions": {}, "fundamentals": {}, "computed_at": "2026-11-08",
    }
    return exhibit.exhibit_a(row)


def _packet(**over):
    packet = {
        "choices": [
            {"choice_id": "act_at_band_low", "label": "Act at the low band",
             "price": 272.18},
            {"choice_id": "act_at_band_mid", "label": "Act at the mid band",
             "price": 310.17},
            {"choice_id": "watch", "label": "Watch", "price": 460.42},
            {"choice_id": "pass", "label": "Pass", "price": 460.42},
        ],
        "rubric_weights": {"guide_credibility": 0.3, "gap_size": 0.25,
                           "direction_momentum": 0.15,
                           "options_expression": 0.1,
                           "falsifier_proximity": 0.2},
        "digest": "Price is 9.69 widths above the guide mid.",
        "proposer_pick": {"choice_id": "act_at_band_mid",
                          "direction": "short", "probability": 0.62},
        "rationale": "The price implies more than the file supports.",
    }
    packet.update(over)
    return packet


def _chat(packet):
    def chat(system, user, *, schema=None):
        if "BULL RESEARCHER" in system:
            return "The guide was raised and the file is conservative.", "fake-qwen"
        if "BEAR RESEARCHER" in system:
            return "The price implies 27.92 against a 19.28 guide high.", "fake-qwen"
        return packet, "fake-qwen"
    return chat


def test_fork_runs_bull_bear_then_structures_a_valid_packet():
    out = debate_fork.run_debate(_ex(), chat=_chat(_packet()))
    assert "conservative" in out["bull_case"]
    assert "27.92" in out["bear_case"]
    packet = out["packet"]
    assert packet["proposer_pick"]["direction"] == "short"
    weights = packet["rubric_weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-6  # normalized by code


def test_fork_rejects_an_invented_choice_price():
    bad = _packet()
    bad["choices"] = [dict(c) for c in bad["choices"]]
    bad["choices"][1]["price"] = 999.99  # not a band price: voids the verdict
    with pytest.raises(debate_fork.PacketInvalid):
        debate_fork.run_debate(_ex(), chat=_chat(bad))


def test_fork_rejects_a_pick_outside_the_choices():
    bad = _packet(proposer_pick={"choice_id": "yolo", "direction": "short",
                                 "probability": 0.5})
    with pytest.raises(debate_fork.PacketInvalid):
        debate_fork.run_debate(_ex(), chat=_chat(bad))


def test_fork_caps_the_digest_at_the_frozen_token_budget():
    big = _packet(digest="x" * 100_000)
    out = debate_fork.run_debate(_ex(), chat=_chat(big))
    assert len(out["packet"]["digest"]) <= debate_fork.DIGEST_CHAR_CAP
    assert out["packet"]["digest_truncated"] is True
