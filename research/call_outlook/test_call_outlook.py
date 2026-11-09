"""Unit tests for call_outlook pure functions."""

from __future__ import annotations

import pytest

from research.call_outlook.statements import (
    prefilter,
    verify,
    score,
    Statement,
    Topic,
    Direction,
    Horizon,
)


def test_prefilter_keeps_cue_sentences():
    """Prefilter should keep sentences with forward cues."""
    text = "We expect revenue to grow. The weather is nice. We anticipate higher margins."
    result = prefilter(text)
    assert "expect revenue to grow" in result.lower()
    assert "anticipate higher margins" in result.lower()
    assert "weather is nice" not in result.lower()


def test_prefilter_caps_at_6000_words():
    """Prefilter should cap at 6000 words."""
    # Create a sentence with a cue and repeat it many times
    sentence = "We expect growth. "
    text = sentence * 10000  # ~20000 words
    result = prefilter(text)
    words = result.split()
    assert len(words) <= 6000


def test_prefilter_drops_sentences_without_cues():
    """Prefilter should drop sentences without forward cues."""
    text = "The weather is nice. We expect growth. It rained yesterday."
    result = prefilter(text)
    assert "expect growth" in result.lower()
    assert "weather is nice" not in result.lower()
    assert "rained yesterday" not in result.lower()


def test_verify_keeps_valid_quote():
    """Verify should keep statements with valid quotes in text."""
    call_text = "We expect revenue to grow 10% next quarter."
    statements = [
        {
            "topic": "revenue",
            "direction": "up",
            "magnitude_pct": 10.0,
            "horizon": "next_quarter",
            "quote": "We expect revenue to grow 10% next quarter.",
        }
    ]
    kept, dropped = verify(statements, call_text)
    assert len(kept) == 1
    assert dropped == 0


def test_verify_drops_quote_not_in_text():
    """Verify should drop statements with quotes not in text."""
    call_text = "We expect revenue to grow."
    statements = [
        {
            "topic": "revenue",
            "direction": "up",
            "magnitude_pct": None,
            "horizon": "next_quarter",
            "quote": "We expect revenue to shrink.",  # not in text
        }
    ]
    kept, dropped = verify(statements, "We expect revenue to grow.")
    assert len(kept) == 0
    assert dropped == 1


def test_verify_drops_mismatched_magnitude():
    """Verify should drop if magnitude_pct not in quote."""
    call_text = "We expect revenue to grow 10% next quarter."
    statements = [
        {
            "topic": "revenue",
            "direction": "up",
            "magnitude_pct": 20.0,  # 20% not in quote
            "horizon": "next_quarter",
            "quote": "We expect revenue to grow 10% next quarter.",
        }
    ]
    kept, dropped = verify(statements, call_text)
    assert len(kept) == 0
    assert dropped == 1


def test_verify_keeps_without_magnitude():
    """Verify should keep statements without magnitude_pct."""
    call_text = "We expect revenue to grow next quarter."
    statements = [
        {
            "topic": "revenue",
            "direction": "up",
            "magnitude_pct": None,
            "horizon": "next_quarter",
            "quote": "We expect revenue to grow next quarter.",
        }
    ]
    kept, dropped = verify(statements, call_text)
    assert len(kept) == 1
    assert dropped == 0


def test_score_signs():
    """Test scoring with various topics and directions."""
    # revenue up = +1
    statements = [
        {"topic": "revenue", "direction": "up", "horizon": "next_quarter", "magnitude_pct": None},
    ]
    assert score(statements) == 1.0
    
    # costs up = -1
    statements = [
        {"topic": "costs", "direction": "up", "horizon": "next_quarter", "magnitude_pct": None},
    ]
    assert score(statements) == -1.0
    
    # tariffs down = +1
    statements = [
        {"topic": "tariffs", "direction": "down", "horizon": "next_quarter", "magnitude_pct": None},
    ]
    assert score(statements) == 1.0
    
    # flat = 0
    statements = [
        {"topic": "revenue", "direction": "flat", "horizon": "next_quarter", "magnitude_pct": None},
    ]
    assert score(statements) == 0.0
    
    # other = excluded
    statements = [
        {"topic": "other", "direction": "up", "horizon": "next_quarter", "magnitude_pct": None},
    ]
    assert score(statements) is None
    
    # wrong horizon = excluded
    statements = [
        {"topic": "revenue", "direction": "up", "horizon": "longer", "magnitude_pct": None},
    ]
    assert score(statements) is None


def test_score_mixed():
    """Test scoring with mixed statements."""
    statements = [
        {"topic": "revenue", "direction": "up", "horizon": "next_quarter", "magnitude_pct": None},  # +1
        {"topic": "costs", "direction": "up", "horizon": "next_quarter", "magnitude_pct": None},   # -1
        {"topic": "eps", "direction": "down", "horizon": "next_quarter", "magnitude_pct": None},   # -1
    ]
    # (+1) + (-1) + (-1) = -1, divided by 3 = -0.333...
    assert abs(score(statements) - (-1/3)) < 1e-9


def test_score_empty():
    """Empty statements returns None."""
    assert score([]) is None


def test_score_wrong_horizon_excluded():
    """Statements with wrong horizon should be excluded."""
    statements = [
        {"topic": "revenue", "direction": "up", "horizon": "longer", "magnitude_pct": None},
    ]
    assert score(statements) is None


def test_verify_drops_empty_quote():
    """Verify should drop statements with empty quotes."""
    call_text = "We expect revenue to grow."
    statements = [
        {
            "topic": "revenue",
            "direction": "up",
            "magnitude_pct": None,
            "horizon": "next_quarter",
            "quote": "",
        }
    ]
    kept, dropped = verify(statements, call_text)
    assert len(kept) == 0
    assert dropped == 1


def test_extraction_cache_skips_cached_call(tmp_path, monkeypatch):
    """The extraction cache should skip already cached calls.

    Hermetic (2026-11-08): extract_call routes through the opencode CLI, which
    exists on Kevin's Mac but not in CI, so the model call is faked here; and
    _load_cache globs CACHE_DIR while _save_cache_entry appends to
    EXTRACTIONS_CACHE, so both are pointed at one tmp dir. The skip is proven
    by the model being called exactly once across two extract_call calls.
    """
    import research.call_outlook.extract as extract_mod

    monkeypatch.setattr(extract_mod, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(extract_mod, "EXTRACTIONS_CACHE", tmp_path / "extractions.jsonl")

    calls = []

    def fake_post_opencode(text, *, model):
        calls.append(model)
        return {"statements": [
            {"topic": "revenue", "direction": "up", "magnitude_pct": 10.0,
             "horizon": "next_quarter", "quote": "We expect revenue to grow 10%."}
        ], "model": "test-model"}

    monkeypatch.setattr(extract_mod, "_post_opencode", fake_post_opencode)

    call_id = "AAPL-2023-01-01"
    statements1 = extract_mod.extract_call(call_id, "We expect revenue to grow 10%.", "test-key")
    assert len(statements1) == 1

    # Second call with same ID should use cache, not the model
    statements2 = extract_mod.extract_call(call_id, "We expect revenue to grow 10%.", "test-key")
    assert statements2 == statements1
    assert len(calls) == 1

def test_flat_other_and_capex_do_not_dilute_the_score():
    from research.call_outlook.statements import score
    sts = [{"topic": "revenue", "direction": "up", "horizon": "next_quarter"},
           {"topic": "other", "direction": "flat", "horizon": "next_quarter"},
           {"topic": "capex", "direction": "up", "horizon": "full_year"},
           {"topic": "guidance", "direction": "down", "horizon": "full_year"},
           {"topic": "guidance", "direction": "flat", "horizon": "full_year"}]
    assert score(sts) == 0.0  # (+1 - 1 + 0) / 3
