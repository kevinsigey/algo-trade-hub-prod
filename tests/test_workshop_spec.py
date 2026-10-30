from datetime import date

import pytest
from pydantic import ValidationError

from tradehub.workshop.spec import IdeaSpec, blank_spec

GOLD = {
    "title": "Gold beats stocks when rates rise",
    "hold": ["gld"],
    "when": {"source": "fred", "series": "DGS10", "measure": "change", "lookback_days": 63, "op": ">", "threshold": 0.25},
    "otherwise": "SPY",
    "claim": "beats_benchmark_when",
    "assumptions": ["rates rising = 10-year yield up more than 0.25 points over 3 months"],
}


def test_mockup_idea_validates_and_uppercases():
    spec = IdeaSpec.model_validate(GOLD)
    assert spec.hold == ["GLD"] and spec.otherwise == "SPY" and spec.benchmark == "SPY"
    assert spec.cost_bps == 10 and spec.unseen_fraction == 0.3 and spec.start == date(2006, 1, 3)


def test_when_claim_needs_a_condition():
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate({**GOLD, "when": None})


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate({**GOLD, "leverage": 3})


def test_cost_cap_and_bad_ticker():
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate({**GOLD, "cost_bps": 500})
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate({**GOLD, "hold": ["GLD; DROP"]})


def test_cash_otherwise_allowed_and_start_bounds():
    assert IdeaSpec.model_validate({**GOLD, "otherwise": "cash"}).otherwise == "CASH"
    with pytest.raises(ValidationError):
        IdeaSpec.model_validate({**GOLD, "start": "1990-01-01"})


def test_schema_is_closed():
    assert IdeaSpec.model_json_schema()["additionalProperties"] is False


def test_blank_template():
    b = blank_spec()
    assert b["title"] == "" and b["hold"] == [] and b["claim"] == "beats_benchmark" and b["when"] is None
