"""The fork (spec section 4): the TradingAgents debate flow, made ours.

The stock framework takes only (ticker, date) — it has no exhibit channel —
so the fork lives here: the valuation fact sheet is Exhibit A, fixed and
injected verbatim into every stage; a bull researcher argues the file is
conservative or improving, a bear researcher argues the price implies more
than the file, and a pinned-class structurer (the proposer) turns the
argument into a typed decision problem: the four canonical choices whose
prices ARE the band prices, rubric weights, a state digest inside the frozen
token budget, and its own pick — logged on every verdict as a grading
control. The structurer does NOT decide unless the seat is the free AI
version (judge.py).

Code validates the packet against the fact sheet: a choice price that is not
a band price (or the live price, for watch/pass) voids the verdict — the
"tighten, never invent" rule enforced by construction.
"""
from __future__ import annotations

from pydantic import BaseModel

from tradehub.valuation import exhibit as exhibit_mod

DIGEST_CHAR_CAP = 32_000  # the frozen <=8k-token state digest, in chars
RUBRIC_KEYS = ("guide_credibility", "gap_size", "direction_momentum",
               "options_expression", "falsifier_proximity")
CHOICE_IDS = ("act_at_band_low", "act_at_band_mid", "watch", "pass")

BULL_SYSTEM = (
    "You are the BULL RESEARCHER in a valuation debate. The only facts you "
    "may use are in Exhibit A, the company's valuation fact sheet, given "
    "verbatim below your instructions. Argue that the recorded guidance file "
    "is conservative or improving: guide direction, the gap between what the "
    "price implies and what the guide supports, the quality of the anchor. "
    "Cite only numbers that appear in Exhibit A — invent nothing, round "
    "nothing. Write the bull case in plain prose, at most four paragraphs."
)
BEAR_SYSTEM = (
    "You are the BEAR RESEARCHER in a valuation debate. The only facts you "
    "may use are in Exhibit A, the company's valuation fact sheet, given "
    "verbatim below your instructions. Argue that the price implies more "
    "than the file supports: the implied figure against the guide range, the "
    "distance to the bands, what the falsifier would do to the bands. Cite "
    "only numbers that appear in Exhibit A — invent nothing, round nothing. "
    "Write the bear case in plain prose, at most four paragraphs."
)
STRUCTURER_SYSTEM = (
    "You are the STRUCTURER of a valuation debate. From Exhibit A and the "
    "bull and bear cases, build the typed decision problem and log your own "
    "pick. The choices are fixed and their prices are the fact sheet's own "
    "numbers, copied exactly: act_at_band_low at the bear band, "
    "act_at_band_mid at the base band, watch and pass at the current price. "
    "Weights for the five rubric criteria must each be between 0 and 1. The "
    "digest is the whole state (fact sheet + debate) in at most 6000 "
    "characters. Your proposer_pick is your own call — it is logged as a "
    "grading control. Reply with JSON only, matching the schema."
)


class Choice(BaseModel):
    choice_id: str
    label: str
    price: float


class ProposerPick(BaseModel):
    choice_id: str
    direction: str  # long | short | none
    probability: float | None = None


class DecisionPacket(BaseModel):
    choices: list[Choice]
    rubric_weights: dict[str, float]
    digest: str
    proposer_pick: ProposerPick
    rationale: str = ""


class PacketInvalid(Exception):
    """The structured packet failed validation against the fact sheet;
    the verdict is void (spec section 4), never repaired by guessing."""


def _expected_prices(ex: dict) -> dict[str, float]:
    bands = ex.get("bands") or {}
    return {
        "act_at_band_low": float(bands["bear"]),
        "act_at_band_mid": float(bands["base"]),
        "watch": float(ex["price"]),
        "pass": float(ex["price"]),
    }


def validate_packet(raw, ex: dict) -> dict:
    """Validate + normalize a structurer reply against Exhibit A. Returns the
    packet as a plain dict (weights normalized to sum 1, digest capped)."""
    try:
        packet = DecisionPacket.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        raise PacketInvalid(f"packet does not fit the contract: {exc}") \
            from exc
    expected = _expected_prices(ex)
    seen = {}
    for choice in packet.choices:
        if choice.choice_id not in expected:
            raise PacketInvalid(f"unknown choice {choice.choice_id!r}")
        if abs(choice.price - expected[choice.choice_id]) > 0.011:
            raise PacketInvalid(
                f"choice {choice.choice_id} price {choice.price} is not "
                f"the fact sheet's {expected[choice.choice_id]} — "
                "an invented number voids the verdict")
        seen[choice.choice_id] = choice
    if set(seen) != set(expected):
        raise PacketInvalid(
            f"choices must be exactly {sorted(expected)}, got {sorted(seen)}")
    weights = {}
    for key in RUBRIC_KEYS:
        if key not in packet.rubric_weights:
            raise PacketInvalid(f"rubric weight {key} missing")
        val = float(packet.rubric_weights[key])
        if not 0.0 <= val <= 1.0:
            raise PacketInvalid(f"rubric weight {key}={val} outside [0, 1]")
        weights[key] = val
    total = sum(weights.values())
    if total <= 0:
        raise PacketInvalid("rubric weights sum to zero")
    weights = {k: round(v / total, 6) for k, v in weights.items()}
    pick = packet.proposer_pick
    if pick.choice_id not in expected:
        raise PacketInvalid(f"proposer pick {pick.choice_id!r} is not a "
                            "declared choice")
    if pick.direction not in ("long", "short", "none"):
        raise PacketInvalid(f"proposer direction {pick.direction!r} invalid")
    if pick.probability is not None and not 0.0 <= pick.probability <= 1.0:
        raise PacketInvalid("proposer probability outside [0, 1]")
    digest = packet.digest or ""
    truncated = len(digest) > DIGEST_CHAR_CAP
    if truncated:
        digest = digest[:DIGEST_CHAR_CAP]
    return {
        "choices": [{"choice_id": c.choice_id, "label": c.label,
                     "price": c.price}
                    for c in packet.choices],
        "rubric_weights": weights,
        "digest": digest,
        "digest_truncated": truncated,
        "proposer_pick": {"choice_id": pick.choice_id,
                          "direction": pick.direction,
                          "probability": pick.probability},
        "rationale": packet.rationale or "",
    }


def run_debate(ex: dict, *, chat) -> dict:
    """One forked debate over Exhibit A. chat(system, user, schema=None) ->
    (content, model_id), the valuation llm module's contract. Returns the
    bull/bear prose and the validated packet. PacketInvalid propagates (the
    caller logs a void verdict); LLMUnavailable likewise."""
    exhibit_md = exhibit_mod.render_markdown(ex)
    bull, _m1 = chat(BULL_SYSTEM,
                     f"{exhibit_md}\n\nWrite the bull case.", schema=None)
    bear, _m2 = chat(BEAR_SYSTEM,
                     f"{exhibit_md}\n\nThe bull case, for rebuttal:\n{bull}"
                     "\n\nWrite the bear case.", schema=None)
    raw, model = chat(
        STRUCTURER_SYSTEM,
        f"{exhibit_md}\n\n## Bull case\n{bull}\n\n## Bear case\n{bear}\n\n"
        "Build the decision packet.",
        schema=DecisionPacket.model_json_schema())
    packet = validate_packet(raw, ex)
    return {"bull_case": bull, "bear_case": bear, "packet": packet,
            "proposer_model": model}
