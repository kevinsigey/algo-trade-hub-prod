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
    assert b["title"] == "" and b["hold"] == [] and b["claim"] == "beats_benchmark" and b["rules"] is None


def test_short_legs_and_execution():
    from tradehub.workshop.spec import IdeaSpec
    s = IdeaSpec(title="Short QQQ", hold=[], short=["qqq"], claim="beats_benchmark")
    assert s.short == ["QQQ"] and s.execution.order_type == "market" and s.execution.timing == "open"
    pair = IdeaSpec(title="Gold vs stocks", hold=["GLD"], short=["SPY"], claim="beats_benchmark",
                    execution={"order_type": "limit", "timing": "close", "limit_offset_bps": 20})
    assert pair.execution.limit_offset_bps == 20
    with pytest.raises(ValueError, match="both"):
        IdeaSpec(title="x both", hold=["GLD"], short=["gld"], claim="beats_benchmark")
    with pytest.raises(ValueError, match="needs a position"):
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
    IdeaSpec(title="one leg", hold=[], short=["QQQ"], claim="beats_benchmark",
             exits={"stop_loss_pct": 5, "take_profit_pct": 10, "max_days": 20, "mode": "intraday"})
    # Alpaca holds a position's shares for one resting exit: a trailing stop can't sit beside another exit.
    for combo in ({"trailing_pct": 8, "stop_loss_pct": 5}, {"trailing_pct": 8, "take_profit_pct": 10}):
        with pytest.raises(ValueError, match="trailing"):
            IdeaSpec(title="one leg", hold=["GLD"], claim="beats_benchmark", exits={**combo, "mode": "intraday"})
    with pytest.raises(ValueError, match="needs a price exit"):
        IdeaSpec(title="one leg", hold=["GLD"], claim="beats_benchmark", exits={"max_days": 5, "mode": "intraday"})
    with pytest.raises(ValueError, match="one ticker"):
        IdeaSpec(title="pair", hold=["GLD"], short=["SPY"], claim="beats_benchmark",
                 exits={"stop_loss_pct": 5, "mode": "intraday"})


PRICE = {"source": "price", "series": "SPY", "measure": "rsi", "lookback_days": 14, "op": "<", "threshold": 30}


def test_legacy_when_becomes_rules():
    s = IdeaSpec.model_validate(GOLD)
    assert s.rules.enter.mode == "all" and s.rules.exit is None
    assert s.rules.enter.conditions[0].model_dump() == {**GOLD["when"], "slow_days": None}
    assert "when" not in s.model_dump()


def test_when_and_rules_refused():
    with pytest.raises(ValidationError, match="both"):
        IdeaSpec.model_validate({**GOLD, "rules": {"enter": {"conditions": [PRICE]}}})


def test_cross_needs_slow_gt_fast():
    cross = {**PRICE, "measure": "sma_cross", "lookback_days": 50, "op": ">", "threshold": 0}
    IdeaSpec(title="SPY golden cross", hold=["SPY"], claim="beats_benchmark",
             rules={"enter": {"conditions": [{**cross, "slow_days": 200}]}})
    for slow in (None, 50, 20):
        with pytest.raises(ValidationError, match="slow"):
            IdeaSpec(title="SPY golden cross", hold=["SPY"], claim="beats_benchmark",
                     rules={"enter": {"conditions": [{**cross, "slow_days": slow}]}})


def test_measure_source_matrix():
    def spec(c):
        return IdeaSpec(title="matrix", hold=["SPY"], claim="beats_benchmark", rules={"enter": {"conditions": [c]}})
    spec(PRICE)
    spec({**PRICE, "source": "fred", "series": "DGS10", "measure": "vs_sma"})
    spec({**PRICE, "source": "analyst", "series": "AAPL", "measure": "net_upgrades"})
    for bad in ({**PRICE, "source": "fred", "measure": "vs_vwap"}, {**PRICE, "measure": "net_upgrades"},
                {**PRICE, "source": "analyst", "measure": "rsi"}):
        with pytest.raises(ValidationError):
            spec(bad)


def test_group_size_1_to_5():
    for n in (0, 6):
        with pytest.raises(ValidationError):
            IdeaSpec(title="sizes", hold=["SPY"], claim="beats_benchmark",
                     rules={"enter": {"mode": "any", "conditions": [PRICE] * n}})
    IdeaSpec(title="sizes", hold=["SPY"], claim="beats_benchmark", rules={"enter": {"conditions": [PRICE] * 5}})


def test_spec_roundtrip_dump():
    s = IdeaSpec(title="RSI dip", hold=["SPY"], claim="beats_benchmark",
                 rules={"enter": {"conditions": [PRICE]},
                        "exit": {"mode": "any", "conditions": [{**PRICE, "op": ">", "threshold": 60}]}})
    assert IdeaSpec.model_validate(s.model_dump(mode="json")) == s
