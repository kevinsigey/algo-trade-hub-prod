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

    source: Literal["fred", "price", "analyst"]
    series: str = Field(min_length=1, max_length=30)
    measure: Literal["level", "change", "pct_change", "vs_sma", "sma_cross", "rsi", "macd", "vs_high", "vs_low",
                     "volatility", "vs_vwap", "net_upgrades", "target_upside"]
    lookback_days: int = Field(63, ge=1, le=756)
    slow_days: int | None = Field(None, ge=2, le=756)  # sma_cross only: the slow average; lookback_days is the fast one
    op: Literal[">", "<"]
    threshold: float

    @field_validator("series")
    @classmethod
    def _series(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9][A-Z0-9.\-_]{0,29}$", v):
            raise ValueError(f"not a series id: {v!r}")
        return v

    @model_validator(mode="after")
    def _fits(self) -> Condition:
        if self.measure not in MEASURES[self.source]:
            raise ValueError(f"{self.measure} can't be measured on a {self.source} series")
        if self.measure == "sma_cross" and (self.slow_days is None or self.slow_days <= self.lookback_days):
            raise ValueError("sma_cross needs slow_days longer than lookback_days")
        return self


MEASURES = {
    "fred": {"level", "change", "pct_change", "vs_sma", "volatility"},
    "price": {"level", "change", "pct_change", "vs_sma", "sma_cross", "rsi", "macd", "vs_high", "vs_low",
              "volatility", "vs_vwap"},
    "analyst": {"net_upgrades", "target_upside"},
}


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "any"] = "all"
    conditions: list[Condition] = Field(min_length=1, max_length=5)


class Rules(BaseModel):
    """Step 6: in when `enter` holds; with an `exit` group, stay in until `exit` holds (exit wins a tie).
    Without one, in only while `enter` holds."""
    model_config = ConfigDict(extra="forbid")

    enter: Group
    exit: Group | None = None


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


class Portfolio(BaseModel):
    """Test the idea inside a portfolio (Kevin, 2026-10-31): each day `idea_share` of the money follows the idea and
    the rest sits in `core` (equal weight), rebalanced daily. The blend is what gets judged and traded."""
    model_config = ConfigDict(extra="forbid")

    core: list[str] = Field(default_factory=lambda: ["SPY"], min_length=1, max_length=5)
    idea_share: float = Field(0.5, ge=0.1, le=0.9)

    @field_validator("core")
    @classmethod
    def _core(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(_ticker(t) for t in v))


class IdeaSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    hold: list[str] = Field(default_factory=list, max_length=25)
    short: list[str] = Field(default_factory=list, max_length=25)
    rules: Rules | None = None
    otherwise: str = CASH
    claim: Literal["beats_benchmark", "beats_benchmark_when", "ballast", "smoother_ride"]
    benchmark: str = "SPY"
    cost_bps: float = Field(10, ge=0, le=200)  # commission per switch
    slippage_bps: float = Field(0, ge=0, le=200)  # extra fill cost per switch, on top of cost_bps
    borrow_bps_yr: float = Field(25, ge=0, le=5000)  # yearly fee to borrow a short leg, charged each day it is held
    start: date = date(2006, 1, 3)
    unseen_fraction: float = Field(0.3, ge=0.1, le=0.5)
    assumptions: list[str] = []
    execution: Execution = Field(default_factory=Execution)
    exits: Exits = Field(default_factory=Exits)
    portfolio: Portfolio | None = None

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

    @model_validator(mode="before")
    @classmethod
    def _legacy_when(cls, data):
        # Steps 2-5 stored one `when` condition; it is a one-condition buy rule with no sell rule.
        if isinstance(data, dict) and "when" in data:
            data = dict(data)
            when = data.pop("when")
            if when is not None:
                if data.get("rules") is not None:
                    raise ValueError("give either 'when' or 'rules', not both")
                data["rules"] = {"enter": {"mode": "all", "conditions": [when]}}
        return data

    @model_validator(mode="after")
    def _claim_needs_condition(self) -> IdeaSpec:
        if not self.hold and not self.short:
            raise ValueError("hold or short needs at least one ticker")
        if set(self.hold) & set(self.short):
            raise ValueError("a ticker can't be both held and shorted")
        if self.exits.mode == "intraday" and len(self.hold) + len(self.short) != 1:
            raise ValueError("intraday stops are for an idea with exactly one ticker (one hold or one short)")
        if self.exits.mode == "intraday" and self.portfolio is not None:
            raise ValueError("intraday stops are not for portfolio ideas (a stop would also sell the core's shares)")
        if self.exits.mode == "intraday":
            e = self.exits
            if e.trailing_pct and (e.stop_loss_pct or e.take_profit_pct):
                raise ValueError("intraday: a trailing stop can't sit beside another exit (Alpaca holds the shares "
                                 "for one resting exit); a stop and a take-profit can, as one-cancels-other")
            if not (e.stop_loss_pct or e.trailing_pct or e.take_profit_pct):
                raise ValueError("intraday mode needs a price exit (stop-loss, trailing or take-profit)")
        if self.claim == "beats_benchmark_when" and self.rules is None:
            raise ValueError("beats_benchmark_when needs a buy rule")
        if self.benchmark == CASH:
            raise ValueError("the benchmark must be a ticker")
        return self


def blank_spec() -> dict:
    """The hand-fill template: what the form starts from when the AI cannot draft."""
    return {"title": "", "hold": [], "short": [], "rules": None, "otherwise": CASH, "claim": "beats_benchmark", "benchmark": "SPY",
            "cost_bps": 10, "start": "2006-01-03", "unseen_fraction": 0.3, "assumptions": []}
