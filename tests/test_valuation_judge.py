"""The decision seat (frozen Nov 8 design): the AI proposes, the decision
model decides. Until a credited OpenRouter key exists, the seat is the free
AI version — the proposer renders the verdict itself — and every verdict
carries which judge rendered it. Jev drops in behind the same interface."""
import pytest

from tradehub.valuation import judge

PACKET = {
    "choices": [
        {"choice_id": "act_at_band_low", "label": "Act at the low band", "price": 272.18},
        {"choice_id": "act_at_band_mid", "label": "Act at the mid band", "price": 310.17},
        {"choice_id": "watch", "label": "Watch", "price": 460.42},
        {"choice_id": "pass", "label": "Pass", "price": 460.42},
    ],
    "rubric_weights": {"guide_credibility": 0.3, "gap_size": 0.25,
                       "direction_momentum": 0.15, "options_expression": 0.1,
                       "falsifier_proximity": 0.2},
    "digest": "AMGN trades 9.7 guide-range widths above its guide mid.",
    "proposer_pick": {"choice_id": "act_at_band_mid", "direction": "short",
                      "probability": 0.62},
    "rationale": "The price implies far more than the guide supports.",
}


def test_free_ai_seat_renders_the_proposers_pick_and_names_itself():
    seat = judge.FreeAiSeat()
    decision = seat.render(PACKET)
    assert seat.judge_id == "free-ai-proposer"
    assert decision["choice_id"] == "act_at_band_mid"
    assert decision["direction"] == "short"
    assert decision["probability"] == 0.62
    assert decision["rationale"]


def test_default_seat_is_the_free_ai_version():
    assert isinstance(judge.seat_for_env({}), judge.FreeAiSeat)
    assert isinstance(judge.seat_for_env({"VALUATION_JUDGE": ""}),
                      judge.FreeAiSeat)


def test_jev_seat_without_a_decisions_client_is_unavailable_not_silent():
    seat = judge.seat_for_env({"VALUATION_JUDGE": "jev"})
    assert seat.judge_id == "jev:typesafe/jev-1.13"
    with pytest.raises(judge.SeatUnavailable) as exc:
        seat.render(PACKET)
    assert "credit" in str(exc.value).lower()


def test_jev_seat_delegates_to_a_decisions_client_when_wired():
    class _Client:
        def decide(self, packet):
            return {"choice_id": "watch", "direction": "none",
                    "probability": None, "rationale": "jev: no edge"}

    seat = judge.JevSeat(client=_Client())
    decision = seat.render(PACKET)
    assert decision["choice_id"] == "watch"
    assert seat.judge_id == "jev:typesafe/jev-1.13"


def _decision(**over):
    base = {"choice_id": "act_at_band_mid", "direction": "short",
            "probability": 0.62, "rationale": "The price implies too much."}
    base.update(over)
    return base


def test_validate_decision_rejects_an_empty_rationale():
    for blank in ("", "   \n  ", None):
        with pytest.raises(judge.DecisionInvalid, match="empty rationale"):
            judge.validate_decision(_decision(rationale=blank))


def test_validate_decision_forces_none_for_watch_with_a_direction():
    cleaned = judge.validate_decision(_decision(
        choice_id="watch", direction="long", probability=0.9))
    assert cleaned["direction"] == "none"
    assert cleaned["probability"] is None
    assert cleaned["choice_id"] == "watch"


def test_validate_decision_rejects_an_act_without_a_direction():
    with pytest.raises(judge.DecisionInvalid, match="act without a direction"):
        judge.validate_decision(_decision(
            choice_id="act_at_band_low", direction="none"))


@pytest.mark.parametrize("probability", [0.4, None])
def test_validate_decision_rejects_an_act_without_usable_probability(
        probability):
    with pytest.raises(judge.DecisionInvalid, match="above 0.5"):
        judge.validate_decision(_decision(probability=probability))


def test_validate_decision_passes_a_coherent_act_unchanged():
    decision = _decision(choice_id="act_at_band_low", direction="long",
                         probability=0.7)
    assert judge.validate_decision(decision) == decision


def test_consistent_direction_voids_an_act_without_a_direction():
    with pytest.raises(judge.DecisionInvalid):
        judge._consistent_direction("act_at_band_low", "none")
