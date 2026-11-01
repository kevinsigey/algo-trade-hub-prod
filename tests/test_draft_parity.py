"""Drafter/editor/spec parity (phase-3 Workshop pass).

Three surfaces describe the same contract -- tradehub/workshop/spec.py's
MEASURES (what the engine runs), the editor's MEASURES table in
market_sentiment_tool/src/lib/workshop.ts (what Kevin can click), and the
drafter's SYSTEM prose in draft.py (what the drafting model is told). Phase 2
added `revision` to the first two and silently not the third, so the agentic
builder simply never proposed it. This test walks all three and fails the
moment they drift again.
"""
from __future__ import annotations

import re
from pathlib import Path

from tradehub.workshop import draft
from tradehub.workshop.spec import MEASURES

ROOT = Path(__file__).resolve().parents[1]
WORKSHOP_TS = ROOT / "market_sentiment_tool" / "src" / "lib" / "workshop.ts"

_SOURCE_SETS = {
    "P": {"price"},
    "FP": {"fred", "price", "spread"},
    "ANY": {"fred", "price", "spread"},
    "WITH_NEWS": {"fred", "price", "spread", "news"},
}


def _frontend_measures() -> dict[str, set[str]]:
    text = WORKSHOP_TS.read_text()
    out: dict[str, set[str]] = {}
    for value, sources in re.findall(r'\{ value: "(\w+)",[^}]*sources: (\[[^\]]*\]|\w+) \}', text):
        if sources.startswith("["):
            srcs = set(re.findall(r'"(\w+)"', sources))
        else:
            srcs = _SOURCE_SETS[sources]
        out[value] = srcs
    return out


def _backend_measures() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for source, measures in MEASURES.items():
        for m in measures:
            out.setdefault(m, set()).add(source)
    return out


def test_editor_measure_table_matches_the_engine_contract():
    assert _frontend_measures() == _backend_measures()


def test_drafter_prose_names_every_source_and_measure():
    prose = draft.SYSTEM.lower()
    for source in MEASURES:
        assert source in prose, f"drafter prose never mentions source {source}"
    for measure in _backend_measures():
        assert measure in prose, f"drafter prose never mentions measure {measure}"


def test_drafter_prose_names_the_option_leg_fields():
    prose = draft.SYSTEM
    for field in ("strike_pct", "days_to_expiry", "roll_days_left"):
        assert field in prose


def test_drafter_prose_names_the_semantic_idea_vocabulary():
    """The fields a drafting model must understand to use the contract (as
    opposed to structural fields like title/id, which the JSON schema itself
    names): the rule groups, the sizing/portfolio concepts, and every
    condition field."""
    from tradehub.workshop.spec import Condition, OptionLeg
    prose = draft.SYSTEM + draft.ENVELOPE_NOTE
    for field in ("rules", "options", "portfolio", "benchmark"):
        assert field in prose, field
    for field in Condition.model_fields:
        assert field in prose, f"condition field {field} unnamed in the prose"
    for field in OptionLeg.model_fields:
        assert field in prose, f"option-leg field {field} unnamed in the prose"
