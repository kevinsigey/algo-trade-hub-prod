"""The decision seat (frozen design, Nov 8): the AI layer proposes the
choices and weights; the decision model makes the call. The seat is an
interface so the pinned judge drops in without schema or caller changes.

Seats:
- FreeAiSeat — the default until a decision seat is configured: the
  Qwen-class proposer/structurer renders the verdict itself. judge_id
  'free-ai-proposer' is stamped on every verdict it renders, so the
  record never pretends a decision model sat where none did.
- JevSeat — the pinned judge, typesafe/jev-1.13 via the OpenRouter
  Decisions API (~$0.0004/verdict). It renders only when constructed
  with a decisions client (the credited-key wiring is a Kevin-side
  credential step); without one it raises SeatUnavailable rather than
  silently substituting another model.
- KevSeat — the designated successor, seated Nov 11, 2026 on Kevin's
  call (the succession clause: Kev succeeds if the pin is retired).
  Kev is Jared Palmer's open decision model (jaredpalmer/kev-4b, a LoRA
  + pointer head on Qwen3.5-4B, Apache-2.0), served by SiliconFlow over
  OpenRouter's /v1/systemone contract — the same wire shape as Jev at
  the same $0.042/M input price. A live probe from the production
  container answered HTTP 200 (served build kev-4b-20260924) before
  this seat was built. Verdicts it renders carry judge_id
  'kev:jaredpalmer/kev-4b' — a separate judge's record, never blended
  into Jev's or the free AI seat's accounting.
"""
from __future__ import annotations

import json
import os
from typing import Protocol

import requests

SYSTEMONE_URL = "https://openrouter.ai/api/v1/systemone"
KEV_MODEL = "jaredpalmer/kev-4b"
# Kev-4B's context is 8,192 tokens (Jev's is 32k). The packet state is
# small by construction, but a state that would overflow is refused --
# SeatUnavailable, never a silent truncation.
KEV_STATE_TOKEN_BUDGET = 6000

_DIRECTIONS = ("long", "short", "none")


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


def _packet_state(packet: dict) -> str:
    """The System One state for a debate packet: the digest, the four
    choices with their live prices, the rubric weights and the
    proposer's own pick (the decision model sees what the proposer
    proposed; the call is its own). Deterministic key order so the same
    packet always sends the same state."""
    return json.dumps({
        "digest": packet.get("digest") or "",
        "choices": packet.get("choices") or [],
        "rubric_weights": packet.get("rubric_weights") or {},
        "proposer_pick": packet.get("proposer_pick") or {},
        "proposer_rationale": packet.get("rationale") or "",
    }, sort_keys=True)


class SystemOneClient:
    """A decisions client speaking the System One wire shape (TypeSafe's
    contract) to OpenRouter: state + typed questions in, per-option
    probabilities out. One client class serves any decision model id on
    that endpoint; the seat owns which id it is."""

    def __init__(self, model: str, api_key: str, post=None):
        self._model = model
        self._api_key = api_key
        self._post = post or requests.post

    def decide(self, packet: dict) -> dict:
        state = _packet_state(packet)
        if len(state) // 4 > KEV_STATE_TOKEN_BUDGET:
            raise SeatUnavailable(
                f"the packet state (~{len(state) // 4} tokens) exceeds "
                f"the {KEV_STATE_TOKEN_BUDGET}-token budget for "
                f"{self._model}'s context; refusing rather than "
                "truncating the state")
        criteria = {
            c["choice_id"]: f"{c.get('label') or c['choice_id']} "
                            f"at {c.get('price')}"
            for c in packet.get("choices") or []}
        if not criteria:
            raise SeatUnavailable("the packet carries no choices")
        body = {
            "model": self._model,
            "state": state,
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": "Which choice should the decision "
                                    "be for this debate packet?",
                    "criteria": criteria},
                "direction": {
                    "type": "choice",
                    "instructions": "If the decision acts, which "
                                    "direction? Answer none when the "
                                    "decision does not act.",
                    "criteria": {
                        "long": "A long position",
                        "short": "A short position",
                        "none": "No position (watch or pass)"}},
            },
        }
        try:
            resp = self._post(
                SYSTEMONE_URL,
                headers={"Authorization": f"Bearer {self._api_key}",
                         "Content-Type": "application/json"},
                json=body, timeout=60)
        except Exception as exc:  # noqa: BLE001 -- any transport failure
            raise SeatUnavailable(
                f"the System One call to {self._model} failed: "
                f"{type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SeatUnavailable(
                f"the System One call to {self._model} returned HTTP "
                f"{resp.status_code} (401/402 = the OpenRouter key or "
                "its credits)")
        try:
            answers = resp.json()["answers"]
            decision = answers["decision"]
            direction = answers["direction"]
        except Exception as exc:  # noqa: BLE001 -- malformed reply shape
            raise SeatUnavailable(
                f"the System One reply from {self._model} did not carry "
                "decision and direction answers") from exc
        choice_id = decision.get("choice")
        if choice_id not in criteria:
            raise SeatUnavailable(
                f"{self._model} answered an unknown choice "
                f"{choice_id!r}")
        dir_choice = direction.get("choice")
        if dir_choice not in _DIRECTIONS:
            raise SeatUnavailable(
                f"{self._model} answered an unknown direction "
                f"{dir_choice!r}")
        probability = (decision.get("probabilities") or {}).get(choice_id)
        return {
            "choice_id": choice_id,
            "direction": dir_choice,
            "probability": probability,
            # A decision model generates no text; the rationale stays
            # empty and the judge stamp carries the provenance.
            "rationale": "",
        }


class KevSeat:
    """Kev (jaredpalmer/kev-4b) — the successor seat, behind the same
    protocol as Jev. Without a wired client it raises SeatUnavailable
    rather than silently substituting another model, exactly like the
    seat it succeeds."""

    judge_id = "kev:jaredpalmer/kev-4b"

    def __init__(self, client=None):
        self._client = client

    def render(self, packet: dict) -> dict:
        if self._client is None:
            raise SeatUnavailable(
                "the Kev seat needs an OpenRouter key wired in "
                "(OPENROUTER_API_KEY); until then the configured seat "
                "renders no verdicts")
        return self._client.decide(packet)


def seat_for_env(env: dict | None = None) -> DecisionSeat:
    """The seat the environment configures: VALUATION_JUDGE=jev selects the
    pinned judge (unavailable until its client is wired); =kev selects
    the successor seat, wired to OpenRouter when its key is present and
    unavailable (never silently substituted) when it is not; anything
    else is the free AI seat. Never a latest-alias or free-rotation model
    in the decision seat."""
    env = os.environ if env is None else env
    selected = (env.get("VALUATION_JUDGE") or "").strip().lower()
    if selected == "jev":
        return JevSeat()
    if selected == "kev":
        key = (env.get("OPENROUTER_API_KEY") or "").strip()
        if key:
            return KevSeat(client=SystemOneClient(KEV_MODEL, key))
        return KevSeat()
    return FreeAiSeat()
