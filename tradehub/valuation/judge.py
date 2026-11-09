"""The decision seat (frozen design, Nov 8): the AI layer proposes the
choices and weights; the decision model makes the call. The seat is an
interface so the pinned judge drops in without schema or caller changes.

Seats:
- FreeAiSeat — until Kevin loads OpenRouter credits (the key on file is
  dead), the Qwen-class proposer/structurer renders the verdict itself.
  judge_id 'free-ai-proposer' is stamped on every verdict it renders, so the
  record never pretends a decision model sat where none did.
- JevSeat — the pinned judge, typesafe/jev-1.13 via the OpenRouter Decisions
  API (~$0.0004/verdict). It renders only when constructed with a decisions
  client (the credited-key wiring is a Kevin-side credential step); without
  one it raises SeatUnavailable rather than silently substituting another
  model. Kev (free, Apache-2.0) is the designated successor — it will be a
  third seat behind this same protocol, not built now.
"""
from __future__ import annotations

import os
from typing import Protocol


class SeatUnavailable(Exception):
    """The configured seat cannot render (e.g. Jev without credits wired)."""


class DecisionSeat(Protocol):
    judge_id: str

    def render(self, packet: dict) -> dict:
        """packet -> {choice_id, direction, probability, rationale}"""
        ...


class FreeAiSeat:
    """The free AI version of the seat: the proposer's own pick IS the
    verdict. Both are logged on the verdict record — identical by
    construction under this seat, and the record says so via judge_id."""

    judge_id = "free-ai-proposer"

    def render(self, packet: dict) -> dict:
        pick = packet["proposer_pick"]
        return {
            "choice_id": pick["choice_id"],
            "direction": pick["direction"],
            "probability": pick.get("probability"),
            "rationale": packet.get("rationale") or "",
        }


class JevSeat:
    """Jev pinned (typesafe/jev-1.13) over the OpenRouter Decisions API.
    The decisions client is injected; wiring a credited key is Kevin's step
    (Nov 18 reminder), so the default seat is unavailable by design."""

    judge_id = "jev:typesafe/jev-1.13"

    def __init__(self, client=None):
        self._client = client

    def render(self, packet: dict) -> dict:
        if self._client is None:
            raise SeatUnavailable(
                "the Jev seat needs a credited OpenRouter Decisions key "
                "wired in (Kevin-side credential step); until then the "
                "free AI seat renders verdicts")
        decision = self._client.decide(packet)
        return {
            "choice_id": decision["choice_id"],
            "direction": decision["direction"],
            "probability": decision.get("probability"),
            "rationale": decision.get("rationale") or "",
        }


def seat_for_env(env: dict | None = None) -> DecisionSeat:
    """The seat the environment configures: VALUATION_JUDGE=jev selects the
    pinned judge (unavailable until its client is wired); anything else is
    the free AI seat. Never a latest-alias or free-rotation model in the
    decision seat."""
    env = os.environ if env is None else env
    if (env.get("VALUATION_JUDGE") or "").strip().lower() == "jev":
        return JevSeat()
    return FreeAiSeat()
