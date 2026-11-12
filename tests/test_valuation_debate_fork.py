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


# --- A5 (2026-11-11): near-miss repairs -------------------------------------
# Production: 10 of 10 rendered verdicts void, on "rubric weight
# guide_credibility missing" (x5) and "unknown choice 'watch_and_pass'" (x3).
# The parser repairs the deterministic near-misses -- a renamed rubric key,
# one unknown key standing in for one missing key, and the two live-priced
# choices merged into one -- because no number is invented by any of them:
# watch and pass are both priced at the live price by construction. Anything
# ambiguous still voids.

def test_fork_repairs_a_combined_watch_and_pass_choice():
    pkt = _packet()
    pkt["choices"] = [c for c in pkt["choices"]
                      if c["choice_id"] not in ("watch", "pass")]
    pkt["choices"].append({"choice_id": "watch_and_pass",
                           "label": "Watch and pass", "price": 460.42})
    out = debate_fork.run_debate(_ex(), chat=_chat(pkt))
    ids = [c["choice_id"] for c in out["packet"]["choices"]]
    assert sorted(ids) == ["act_at_band_low", "act_at_band_mid",
                           "pass", "watch"]
    prices = {c["choice_id"]: c["price"] for c in out["packet"]["choices"]}
    assert prices["watch"] == prices["pass"] == 460.42


def test_fork_repairs_a_directionless_watch_and_pass_pick():
    pkt = _packet(proposer_pick={"choice_id": "watch_and_pass",
                                 "direction": "none", "probability": 0.5})
    out = debate_fork.run_debate(_ex(), chat=_chat(pkt))
    assert out["packet"]["proposer_pick"]["choice_id"] == "watch"


def test_fork_still_voids_a_directional_watch_and_pass_pick():
    pkt = _packet(proposer_pick={"choice_id": "watch_and_pass",
                                 "direction": "short", "probability": 0.5})
    with pytest.raises(debate_fork.PacketInvalid):
        debate_fork.run_debate(_ex(), chat=_chat(pkt))


def test_fork_repairs_a_renamed_rubric_key():
    weights = {"guidance_credibility": 0.3, "gap_size": 0.25,
               "direction_momentum": 0.15, "options_expression": 0.1,
               "falsifier_proximity": 0.2}
    out = debate_fork.run_debate(_ex(), chat=_chat(_packet(rubric_weights=weights)))
    assert abs(out["packet"]["rubric_weights"]["guide_credibility"] - 0.3) < 1e-6


def test_fork_repairs_one_unknown_rubric_key_for_one_missing():
    weights = {"guide_credibility": 0.3, "gap_size": 0.25,
               "direction_momentum": 0.15, "options_expression": 0.1,
               "falsifier_risk": 0.2}
    out = debate_fork.run_debate(_ex(), chat=_chat(_packet(rubric_weights=weights)))
    assert abs(out["packet"]["rubric_weights"]["falsifier_proximity"] - 0.2) < 1e-6


def test_fork_still_voids_when_two_rubric_keys_are_missing():
    weights = {"guide_credibility": 0.3, "gap_size": 0.25,
               "direction_momentum": 0.15, "something_else": 0.3}
    with pytest.raises(debate_fork.PacketInvalid):
        debate_fork.run_debate(_ex(), chat=_chat(_packet(rubric_weights=weights)))


def test_structurer_schema_names_the_choice_enum_and_rubric_fields():
    schema = debate_fork.DecisionPacket.model_json_schema()
    defs = schema.get("$defs", {})
    choice_props = defs.get("Choice", {}).get("properties", {})
    assert choice_props["choice_id"]["enum"] == list(debate_fork.CHOICE_IDS)
    rubric_props = defs.get("RubricWeights", {}).get("properties", {})
    assert sorted(rubric_props) == sorted(debate_fork.RUBRIC_KEYS)


def test_fork_caps_the_digest_at_the_frozen_token_budget():
    big = _packet(digest="x" * 100_000)
    out = debate_fork.run_debate(_ex(), chat=_chat(big))
    assert len(out["packet"]["digest"]) <= debate_fork.DIGEST_CHAR_CAP
    assert out["packet"]["digest_truncated"] is True
