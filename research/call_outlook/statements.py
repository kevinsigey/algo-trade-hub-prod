"""Pure functions for call outlook statement extraction and scoring.

These functions contain no I/O and can be unit tested independently.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────────────────────────────────────────────
# Forward cues and prefilter
# ──────────────────────────────────────────────────────────────────────────────

FORWARD_CUES = (
    "expect",
    "anticipate",
    "guidance",
    "outlook",
    "forecast",
    "will",
    "should",
    "plan",
    "project",
    "believe",
    "headwind",
    "tailwind",
    "next quarter",
    "next year",
    "second half",
    "full year",
    "fiscal 20",
)

_MAX_WORDS = 6000


def prefilter(text: str) -> str:
    """Keep management sentences that contain a forward cue.

    - Split into sentences (naive split on . ? ! followed by space or end)
    - Keep sentences containing any FORWARD_CUE (case-insensitive)
    - Cap at 6000 words total, keeping sentence order
    """
    if not text:
        return ""
    
    # Split into sentences (naive but effective)
    # Split on . ? ! followed by space or end of string
    sentences = re.split(r"(?<=[.!?])\s+", text)
    
    cue_pattern = re.compile("|".join(re.escape(c) for c in FORWARD_CUES), re.IGNORECASE)
    
    kept_sentences = []
    word_count = 0
    
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if cue_pattern.search(sent):
            words = sent.split()
            if word_count + len(words) > _MAX_WORDS:
                break
            kept_sentences.append(sent)
            word_count += len(words)
    
    return " ".join(kept_sentences)


# ──────────────────────────────────────────────────────────────────────────────
# Statement model
# ──────────────────────────────────────────────────────────────────────────────

class Topic(str, Enum):
    REVENUE = "revenue"
    DEMAND = "demand"
    PRICING = "pricing"
    GROSS_MARGIN = "gross_margin"
    OPERATING_MARGIN = "operating_margin"
    EPS = "eps"
    COSTS = "costs"
    TARIFFS = "tariffs"
    OTHER = "other"


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class Horizon(str, Enum):
    NEXT_QUARTER = "next_quarter"
    FULL_YEAR = "full_year"
    LONGER = "longer"
    UNSPECIFIED = "unspecified"


class Statement(BaseModel):
    """A single forward-looking financial statement from management."""
    
    topic: Topic
    direction: Direction
    magnitude_pct: float | None = None
    horizon: Horizon = Horizon.UNSPECIFIED
    quote: str = ""
    
    @field_validator("quote")
    @classmethod
    def quote_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("quote must not be empty")
        return v.strip()


# ──────────────────────────────────────────────────────────────────────────────
# Verification
# ──────────────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, curly quotes to straight, collapse whitespace."""
    if not text:
        return ""
    text = text.lower()
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_NUM_RE = re.compile(r"[\d,]+\.?\d*")


def _number_tokens(text: str) -> list[float]:
    """Extract number tokens from text (digits with optional commas and decimal point)."""
    tokens = []
    for m in re.finditer(r"[\d,]+\.?\d*", text):
        num_str = m.group().replace(",", "")
        try:
            tokens.append(float(num_str))
        except ValueError:
            pass
    return tokens


def verify(statements: list[dict], call_text: str) -> tuple[list[dict], int]:
    """Verify statements against the call text.

    Keeps a statement only if:
    - Its normalized quote is a substring of the normalized call text
    - If magnitude_pct is given, that number (as float) appears in the quote

    Returns (kept_statements, dropped_count).
    """
    if not statements:
        return [], 0
    
    norm_call = _normalize(call_text)
    kept = []
    dropped = 0
    
    for stmt in statements:
        quote = stmt.get("quote", "")
        if not quote:
            dropped += 1
            continue
        
        norm_quote = _normalize(quote)
        
        # Check quote appears in call text
        if norm_quote not in _normalize(call_text):
            dropped += 1
            continue
        
        # If magnitude_pct is given, it must appear in the quote
        magnitude = stmt.get("magnitude_pct")
        if magnitude is not None:
            quote_numbers = _number_tokens(_normalize(stmt.get("quote", "")))
            if not any(abs(magnitude - n) < 1e-9 for n in quote_numbers):
                dropped += 1
                continue
        
        kept.append(stmt)
    
    return kept, len(statements) - len(kept)


# ──────────────────────────────────────────────────────────────────────────────
# Signs table and scoring
# ──────────────────────────────────────────────────────────────────────────────

# Sign for the stock:
# revenue, demand, pricing, gross_margin, operating_margin, eps: up +1, down -1
# costs, tariffs: up -1, down +1
# flat = 0
# other = excluded (score returns None for that statement)
SIGNS = {
    ("revenue", "up"): +1,
    ("revenue", "down"): -1,
    ("demand", "up"): +1,
    ("demand", "down"): -1,
    ("pricing", "up"): +1,
    ("pricing", "down"): -1,
    ("gross_margin", "up"): +1,
    ("gross_margin", "down"): -1,
    ("operating_margin", "up"): +1,
    ("operating_margin", "down"): -1,
    ("eps", "up"): +1,
    ("eps", "down"): -1,
    ("costs", "up"): -1,
    ("costs", "down"): +1,
    ("tariffs", "up"): -1,
    ("tariffs", "down"): +1,
    # flat is 0 for all
    # other is not in the table -> excluded
}


def score(statements: list[dict]) -> float | None:
    """Score = (sum of signs) / (number of signed statements).

    Only next_quarter and full_year horizons count.
    flat = 0, other = excluded.
    Returns None if no signed statements.
    """
    signed = []
    
    for stmt in statements:
        topic = stmt.get("topic")
        direction = stmt.get("direction")
        horizon = stmt.get("horizon")
        
        # Only next_quarter and full_year horizons count
        if horizon not in ("next_quarter", "full_year"):
            continue
        
        topic_str = str(topic).lower()
        direction_str = str(direction).lower()
        
        if direction_str == "flat":
            signed.append(0)
            continue
        
        sign = SIGNS.get((topic_str, direction_str.lower()))
        if sign is None:
            # other or unknown -> excluded
            continue
        
        signed.append(sign)
    
    if not signed:
        return None
    
    return sum(signed) / len(signed)