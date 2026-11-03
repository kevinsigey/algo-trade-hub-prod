"""In-site agent phase 1: the StrategySpec validator names its failed
fields, the per-name cap is the hub's 25%, and the interpreter returns
questions -- never guesses -- for what the text left open."""
import json

import pytest

from tradehub.agent.interpret import InterpretUnavailable, interpret
from tradehub.agent.spec import validate_spec

VALID = {
    "thesis": "Energy majors are mispriced into the print and the complex rerates after.",
    "catalysts": ["earnings"], "invalidation": ["guide cut"],
    "universe": ["XLE", "XOM"],
    "entry": {"rule": "close_below", "band_pct": 1.5},
    "sizing": {"kind": "pct_of_equity", "value": 10, "per_name_cap_pct": 25},
    "stops": {"kind": "pct", "value": 8},
    "exits": {"take_profit_pct": None, "time_stop_days": None},
    "horizon": {"terminal_date": "2026-11-06"},
    "monitoring": ["price_cross", "terminal_date"],
    "scoring": {"benchmark": "SPY", "review_at": "terminal_date"},
}


def test_valid_spec_passes():
    assert validate_spec(VALID) == []


def test_problems_name_their_fields():
    bad = dict(VALID, universe=[], entry={"rule": "whenever"},
               sizing={"kind": "pct_of_equity", "value": 10, "per_name_cap_pct": 40},
               horizon={"terminal_date": "Nov 6"})
    problems = validate_spec(bad)
    assert any(p.startswith("universe") for p in problems)
    assert any(p.startswith("entry.rule") for p in problems)
    assert any("per_name_cap_pct" in p and "25" in p for p in problems)
    assert any(p.startswith("horizon.terminal_date") for p in problems)


def test_stops_need_a_value_unless_none():
    assert any("stops.value" in p for p in validate_spec(dict(VALID, stops={"kind": "pct"})))
    ok = dict(VALID, stops={"kind": "none", "value": None})
    assert validate_spec(ok) == []


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _gemini_ok(envelope):
    text = json.dumps(envelope)
    return _Resp({"candidates": [{"content": {"parts": [{"text": text}]}}]})


def test_interpret_returns_spec_questions_and_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    envelope = {"spec": VALID, "questions": ["Which book should this run on?"]}
    spec, questions, model = interpret("memo text", post=lambda *a, **k: _gemini_ok(envelope))
    assert spec["universe"] == ["XLE", "XOM"]
    assert questions == ["Which book should this run on?"]
    assert "gemini" in model


def test_interpret_appends_validation_problems_as_questions(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    broken = dict(VALID, sizing={"kind": "pct_of_equity", "value": 10, "per_name_cap_pct": 60})
    envelope = {"spec": broken, "questions": []}
    _, questions, _ = interpret("memo text", post=lambda *a, **k: _gemini_ok(envelope))
    assert any("per_name_cap_pct" in q for q in questions)


def test_interpret_fails_honestly_when_no_model_is_configured(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(InterpretUnavailable) as exc:
        interpret("memo text", post=lambda *a, **k: _gemini_ok({"spec": VALID, "questions": []}))
    assert exc.value.reason == "no_key"
