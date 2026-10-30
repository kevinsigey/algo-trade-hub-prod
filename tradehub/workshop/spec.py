"""The idea-test contract shared by the AI draft, Kevin's edited form and the engine (Trading HQ step 2)."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
CASH = "CASH"


def _ticker(value: str) -> str:
    value = value.strip().upper()
    if not TICKER.match(value):
        raise ValueError(f"not a ticker: {value!r}")
    return value


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["fred", "price"]
    series: str = Field(min_length=1, max_length=30)
    measure: Literal["level", "change", "pct_change"]
    lookback_days: int = Field(63, ge=1, le=756)
    op: Literal[">", "<"]
    threshold: float

    @field_validator("series")
    @classmethod
    def _series(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9.\-_]{0,29}$", v):
            raise ValueError(f"not a series id: {v!r}")
        return v


class IdeaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    hold: list[str] = Field(min_length=1, max_length=5)
    when: Condition | None = None
    otherwise: str = CASH
    claim: Literal["beats_benchmark", "beats_benchmark_when", "ballast", "smoother_ride"]
    benchmark: str = "SPY"
    cost_bps: float = Field(10, ge=0, le=200)
    start: date = date(2006, 1, 3)
    unseen_fraction: float = Field(0.3, ge=0.1, le=0.5)
    assumptions: list[str] = []

    @field_validator("hold")
    @classmethod
    def _hold(cls, v: list[str]) -> list[str]:
        return [_ticker(t) for t in v]

    @field_validator("otherwise", "benchmark")
    @classmethod
    def _one(cls, v: str) -> str:
        return CASH if v.strip().upper() == CASH else _ticker(v)

    @field_validator("start")
    @classmethod
    def _start(cls, v: date) -> date:
        if not date(1995, 1, 1) <= v < date.today():
            raise ValueError("start must be between 1995-01-01 and yesterday")
        return v

    @model_validator(mode="after")
    def _claim_needs_condition(self) -> IdeaSpec:
        if self.claim == "beats_benchmark_when" and self.when is None:
            raise ValueError("beats_benchmark_when needs a 'when' condition")
        if self.benchmark == CASH:
            raise ValueError("the benchmark must be a ticker")
        return self


def blank_spec() -> dict:
    """The hand-fill template: what the form starts from when the AI cannot draft."""
    return {"title": "", "hold": [], "when": None, "otherwise": CASH, "claim": "beats_benchmark", "benchmark": "SPY",
            "cost_bps": 10, "start": "2006-01-03", "unseen_fraction": 0.3, "assumptions": []}
