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


class Execution(BaseModel):
    """How the paper orders go in (step 4). `close` fills a day after the decision, and the engine lags it to match."""
    model_config = ConfigDict(extra="forbid")

    order_type: Literal["market", "limit"] = "market"
    timing: Literal["open", "close", "day"] = "open"
    limit_offset_bps: float = Field(0, ge=0, le=500)


class Exits(BaseModel):
    """Step 5: when an idea gets out regardless of its rule. None = off. Measured on the idea's whole sleeve
    (close mode) or, for a single-leg idea, by real stop orders during the day (intraday mode)."""
    model_config = ConfigDict(extra="forbid")

    stop_loss_pct: float | None = Field(None, gt=0, le=90)
    trailing_pct: float | None = Field(None, gt=0, le=90)
    take_profit_pct: float | None = Field(None, gt=0, le=1000)
    max_days: int | None = Field(None, ge=1, le=756)
    mode: Literal["close", "intraday"] = "close"

    def any(self) -> bool:
        return any(v is not None for v in (self.stop_loss_pct, self.trailing_pct, self.take_profit_pct, self.max_days))


class IdeaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    hold: list[str] = Field(default_factory=list, max_length=5)
    short: list[str] = Field(default_factory=list, max_length=5)
    when: Condition | None = None
    otherwise: str = CASH
    claim: Literal["beats_benchmark", "beats_benchmark_when", "ballast", "smoother_ride"]
    benchmark: str = "SPY"
    cost_bps: float = Field(10, ge=0, le=200)
    start: date = date(2006, 1, 3)
    unseen_fraction: float = Field(0.3, ge=0.1, le=0.5)
    assumptions: list[str] = []
    execution: Execution = Field(default_factory=Execution)
    exits: Exits = Field(default_factory=Exits)

    @field_validator("hold", "short")
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
        if not self.hold and not self.short:
            raise ValueError("hold or short needs at least one ticker")
        if set(self.hold) & set(self.short):
            raise ValueError("a ticker can't be both held and shorted")
        if self.exits.mode == "intraday" and len(self.hold) + len(self.short) != 1:
            raise ValueError("intraday stops are for an idea with exactly one ticker (one hold or one short)")
        if self.claim == "beats_benchmark_when" and self.when is None:
            raise ValueError("beats_benchmark_when needs a 'when' condition")
        if self.benchmark == CASH:
            raise ValueError("the benchmark must be a ticker")
        return self


def blank_spec() -> dict:
    """The hand-fill template: what the form starts from when the AI cannot draft."""
    return {"title": "", "hold": [], "short": [], "when": None, "otherwise": CASH, "claim": "beats_benchmark", "benchmark": "SPY",
            "cost_bps": 10, "start": "2006-01-03", "unseen_fraction": 0.3, "assumptions": []}
