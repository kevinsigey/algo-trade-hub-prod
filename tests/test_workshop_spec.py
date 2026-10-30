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


def test_exits_round_trip_and_bounds():
    from tradehub.workshop.spec import IdeaSpec
    s = IdeaSpec(title="Gold with stops", hold=["GLD"], claim="beats_benchmark",
                 exits={"stop_loss_pct": 8, "trailing_pct": 12, "take_profit_pct": 25, "max_days": 60})
    assert s.exits.stop_loss_pct == 8 and s.exits.max_days == 60 and s.exits.mode == "close" and s.exits.any()
    assert not IdeaSpec(title="plain", hold=["GLD"], claim="beats_benchmark").exits.any()
    for bad in ({"stop_loss_pct": 0}, {"stop_loss_pct": 95}, {"max_days": 0}, {"take_profit_pct": 2000}):
        with pytest.raises(ValueError):
            IdeaSpec(title="bad exit", hold=["GLD"], claim="beats_benchmark", exits=bad)


def test_intraday_exits_need_a_single_leg():
    from tradehub.workshop.spec import IdeaSpec
    with pytest.raises(ValueError, match="not available yet"):  # review I3: nothing runs it until Part B ships
        IdeaSpec(title="one leg", hold=[], short=["QQQ"], claim="beats_benchmark",
                 exits={"stop_loss_pct": 5, "mode": "intraday"})
    with pytest.raises(ValueError, match="one ticker"):
        IdeaSpec(title="pair", hold=["GLD"], short=["SPY"], claim="beats_benchmark",
                 exits={"stop_loss_pct": 5, "mode": "intraday"})
