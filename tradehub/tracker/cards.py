"""The forecast-card store (Thesis v6, spec Section 3).

One card per covered name per print, frozen BEFORE the release. The
freeze is enforced in three places that agree: this store refuses any
card whose freeze instant is at or after `print_at` (a 422 at the
endpoint); the table's trigger refuses every UPDATE, so a stored card
can never be edited; and a correction is a new pre-print card whose
`supersedes_id` points at the card it replaces -- the graded card for a
print is the LATEST pre-print one (`graded_card`), and superseded cards
are never graded.

The two pre-print signals are stored as separate fields and graded
separately (spec Section 3): `whisper_sign`/`whisper_esp` for the
whisper, `money_flow_direction`/`money_flow_evidence` for the money
flow. Nothing in this module combines them into a score, and the write
contract forbids extra fields, so a combined score cannot sneak in at
the endpoint either. A money-flow direction without named evidence
(with a source link) is refused: the spec's signal is the evidence, not
the arrow.

The store stamps `frozen_at` from the same clock the freeze check
reads -- in this architecture the API process is the freezing
authority, and the column default is only a backstop for other
writers.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from tradehub.valuation.classifications import CLASSES as CLASSIFICATIONS

TABLE = "forecast_cards"
THESES = "theses"
WHISPER_SIGNS = ("positive", "negative", "flat")
FLOW_DIRECTIONS = ("inflow", "outflow", "mixed")
PREDICTIONS = ("up", "down", "flat")
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def _instant(value, field: str) -> datetime:
    """Parse an ISO instant; a naive value is read as UTC."""
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(
                f"{field} {value!r} is not an ISO datetime "
                "(expected e.g. 2026-11-20T21:00:00Z)") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _enum(value, allowed, field):
    if value is None:
        return None
    text = str(value).strip().lower()
    if text not in allowed:
        raise ValueError(
            f"{field} {value!r} is not one of {', '.join(allowed)}")
    return text


def _thesis_id(client, slug) -> int:
    text = str(slug or "").strip()
    resp = client.table(THESES).select("id, slug").eq("slug", text).execute()
    rows = resp.data or []
    if not rows:
        raise ValueError(f"no thesis with slug {slug!r}")
    return rows[0]["id"]


def create_card(client, *, ticker, thesis_slug, print_at,
                whisper_esp=None, whisper_sign=None,
                money_flow_direction=None, money_flow_evidence=None,
                guide_position=None, predicted_direction=None,
                opposing_case_ref=None, classification=None,
                supersedes_id=None, now=None) -> dict:
    """Validate and append one frozen forecast card; returns the row.

    Raises ValueError with a named reason on any contract violation --
    the write endpoint turns that into a 422. The freeze rule is the
    first check that can fail a well-formed card: a card at or after
    the release is not a forecast, and no route may store one.
    """
    symbol = str(ticker or "").strip().upper()
    if not _TICKER_RE.match(symbol):
        raise ValueError(
            f"ticker {ticker!r} is not a plain US symbol (1-12 chars, "
            "letters/digits/./-)")
    print_dt = _instant(print_at, "print_at")
    frozen = now or datetime.now(timezone.utc)
    if frozen >= print_dt:
        raise ValueError(
            f"card frozen at {frozen.isoformat()} is at or after the "
            f"release {print_dt.isoformat()}: forecast cards must be "
            "frozen before the print")
    thesis_id = _thesis_id(client, thesis_slug)
    sign = _enum(whisper_sign, WHISPER_SIGNS, "whisper_sign")
    flow = _enum(money_flow_direction, FLOW_DIRECTIONS,
                 "money_flow_direction")
    predicted = _enum(predicted_direction, PREDICTIONS,
                      "predicted_direction")
    klass = _enum(classification, CLASSIFICATIONS, "classification")
    evidence = money_flow_evidence or []
    if not isinstance(evidence, list) or any(
            not isinstance(item, dict) for item in evidence):
        raise ValueError("money_flow_evidence must be a list of objects "
                         "with text and source")
    if flow is not None:
        named = [item for item in evidence
                 if str(item.get("text") or "").strip()
                 and str(item.get("source") or "").strip()]
        if not named:
            raise ValueError(
                "money_flow_direction needs named evidence: at least "
                "one money_flow_evidence item with text and a source "
                "link (the signal is the evidence, not the arrow)")
    if supersedes_id is not None:
        resp = client.table(TABLE).select("*").eq("id", supersedes_id) \
            .execute()
        prior = (resp.data or [None])[0]
        if prior is None:
            raise ValueError(f"no card with id {supersedes_id}")
        if prior["ticker"] != symbol or \
                _instant(prior["print_at"], "print_at") != print_dt:
            raise ValueError(
                "a superseding card must target the same ticker and "
                "print as the card it replaces")
    row = {"ticker": symbol, "thesis_id": thesis_id,
           "print_at": print_dt.isoformat(),
           "frozen_at": frozen.isoformat(),
           "whisper_esp": whisper_esp, "whisper_sign": sign,
           "money_flow_direction": flow, "money_flow_evidence": evidence,
           "guide_position": (str(guide_position).strip() or None)
           if guide_position else None,
           "predicted_direction": predicted,
           "opposing_case_ref": (str(opposing_case_ref).strip() or None)
           if opposing_case_ref else None,
           "classification": klass, "supersedes_id": supersedes_id}
    resp = client.table(TABLE).insert(row).execute()
    return (resp.data or [row])[0]


def list_cards(client, *, limit: int = 100) -> list[dict]:
    """Newest-frozen first, each card marked `superseded` when a later
    card replaces it. The surface reads this; the grader does not (it
    works print by print through `graded_card`)."""
    resp = client.table(TABLE).select("*") \
        .order("frozen_at", desc=True).limit(limit).execute()
    rows = resp.data or []
    replaced = {r.get("supersedes_id") for r in rows
                if r.get("supersedes_id") is not None}
    return [{**r, "superseded": r.get("id") in replaced} for r in rows]


def graded_card(client, ticker, print_at) -> dict | None:
    """The card that grades for (ticker, print_at): the latest card
    frozen strictly before the release. Cards stamped at or after the
    print (no route writes them; the guard is the reader's) and cards
    for other prints never grade."""
    symbol = str(ticker or "").strip().upper()
    target = _instant(print_at, "print_at")
    resp = client.table(TABLE).select("*").eq("ticker", symbol).execute()
    best = None
    for row in resp.data or []:
        if _instant(row["print_at"], "print_at") != target:
            continue
        frozen = row.get("frozen_at")
        if frozen is None or _instant(frozen, "frozen_at") >= target:
            continue
        if best is None or _instant(frozen, "frozen_at") > \
                _instant(best["frozen_at"], "frozen_at"):
            best = row
    return best
