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


def test_short_legs_and_execution():
    from tradehub.workshop.spec import IdeaSpec
    s = IdeaSpec(title="Short QQQ", hold=[], short=["qqq"], claim="beats_benchmark")
    assert s.short == ["QQQ"] and s.execution.order_type == "market" and s.execution.timing == "open"
    pair = IdeaSpec(title="Gold vs stocks", hold=["GLD"], short=["SPY"], claim="beats_benchmark",
                    execution={"order_type": "limit", "timing": "close", "limit_offset_bps": 20})
    assert pair.execution.limit_offset_bps == 20
    with pytest.raises(ValueError, match="both"):
        IdeaSpec(title="x both", hold=["GLD"], short=["gld"], claim="beats_benchmark")
    with pytest.raises(ValueError, match="at least one"):
        IdeaSpec(title="nothing", hold=[], claim="beats_benchmark")
    with pytest.raises(ValueError):
        IdeaSpec(title="bad type", hold=["GLD"], claim="beats_benchmark", execution={"order_type": "stop"})


def test_old_specs_still_load():
    from tradehub.workshop.spec import IdeaSpec
    old = {"title": "Gold", "hold": ["GLD"], "claim": "beats_benchmark", "otherwise": "CASH", "benchmark": "SPY",
           "cost_bps": 10, "start": "2006-01-03", "unseen_fraction": 0.3, "assumptions": [], "when": None}
    s = IdeaSpec.model_validate(old)
    assert s.short == [] and s.execution.timing == "open"
