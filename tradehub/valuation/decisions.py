"""The per-name decision view + verdict chips (Loop Batch 2, charter
workstream 5).

For any name, ONE surface answers four questions:
  know     — what we know: the guidance fact sheet, as recorded.
  systems  — what the systems say: recorded screen membership, the band
             zone, the crossing log, the print classification.
  judgment — the debate verdict (with its judge identity — never dressed
             as a Jev verdict when the free seat rendered it) and the
             band falsifier's standing for the name.
  missing  — what is missing, named. A gap is stated, never proxied
             (scar tissue #8); every block carries the snapshot it came
             from (scar tissue #9).

Placement: the view lives on the Guidance page, inside the name's own
sheet expansion — the fact sheet IS the decision surface's first block,
so the other three blocks belong beside it rather than on a second page
the reader must cross-reference by hand. Screening rows link here.

Display-only: this module reads; it never writes, orders, or promotes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradehub.valuation import candidates as cand_mod
from tradehub.valuation import store as val_store
from tradehub.valuation import verdict_store

_STATUS_GAPS = {
    "no_full_year_guide": "no usable full-year guide on record",
    "guide_rejected": "the recorded guide was rejected by the guards "
                      "(reasons on the sheet)",
    "no_peer_multiple": "the peer group is too small to price bands",
}


def _first_sentence(text: str | None) -> str | None:
    if not text:
        return None
    text = " ".join(str(text).split())
    cut = text.find(". ")
    out = text[:cut + 1] if cut >= 0 else text
    if len(out) > 240:
        out = out[:237].rstrip() + "…"
    return out or None


def dissent_line(row: dict) -> str | None:
    """The one-line dissent on a verdict chip: the opening line of the
    case AGAINST the verdict's direction — the bear's objection to a
    long call, the bull's objection to a short one, and the bear's
    standing objection to a watch/pass."""
    verdict = row.get("verdict") or {}
    if verdict.get("direction") == "short":
        return _first_sentence(row.get("bull_case")) \
            or _first_sentence(row.get("bear_case"))
    return _first_sentence(row.get("bear_case")) \
        or _first_sentence(row.get("bull_case"))


def chip_for(row: dict) -> dict:
    """The compact verdict record (Batch 2 persistence read): name, date,
    verdict, confidence, exhibit snapshot id, judge identity, dissent."""
    verdict = row.get("verdict") or {}
    return {
        "ticker": row.get("ticker"),
        "verdict_id": row.get("id"),
        "rendered_at": row.get("rendered_at"),
        "judge": row.get("judge"),
        "choice_id": verdict.get("choice_id"),
        "direction": verdict.get("direction"),
        "confidence": verdict.get("probability"),
        "rationale": verdict.get("rationale"),
        "dissent": dissent_line(row),
        "snapshot_id": row.get("snapshot_id"),
        "fact_sheet_id": row.get("fact_sheet_id"),
        "trigger": row.get("trigger"),
        "zone": row.get("baseline_verdict"),
    }


def verdict_chips(client) -> dict[str, dict]:
    """Latest RENDERED verdict per ticker, as compact chips. Voids are
    audit rows, not verdicts — they never surface as a name's judgment."""
    chips: dict[str, dict] = {}
    for row in verdict_store.all_verdicts(client):
        if row.get("status") != "rendered":
            continue
        chips.setdefault(row["ticker"], chip_for(row))
    return chips


def _latest_candidate(client, ticker: str) -> dict | None:
    try:
        rows = (client.table(cand_mod.CANDIDATES).select("*")
                .eq("ticker", ticker).execute().data) or []
    except Exception:  # noqa: BLE001 -- pre-migration: no candidate record
        return None
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("state") != "pending",
                             -(r.get("id") or 0)))
    row = rows[0]
    return {"candidate_class": row.get("candidate_class"),
            "priority": row.get("priority"), "state": row.get("state"),
            "snapshot_id": row.get("snapshot_id"),
            "computed_at": row.get("computed_at")}


def _crossings(client, ticker: str) -> list[dict]:
    try:
        return (client.table("band_crossings").select("*")
                .eq("ticker", ticker).order("id", desc=True).limit(5)
                .execute().data) or []
    except Exception:  # noqa: BLE001 -- pre-migration reads as an empty log
        return []


def name_decision(client, ticker: str, *,
                  now: datetime | None = None) -> dict | None:
    """The four-block decision view for one name, or None when the hub
    knows nothing about it at all (no sheet, no screen record, no
    verdict, no candidate) — the API answers 404 rather than inventing
    an empty dossier."""
    now = now or datetime.now(timezone.utc)
    ticker = ticker.strip().upper()
    snap, snap_sheets = val_store.latest_snapshot_sheets(client)
    sheet = next((s for s in snap_sheets if s.get("ticker") == ticker),
                 None)
    if sheet is None:
        sheet = val_store.latest_sheet(client, ticker)
    contexts = cand_mod.screen_contexts(client, now=now)
    ctx = contexts.get(ticker) or {"screens": [], "entrants": [],
                                   "survivor": False}
    verdict_rows = [r for r in verdict_store.verdicts_for(client, ticker)
                    if r.get("status") == "rendered"]
    chip = chip_for(verdict_rows[0]) if verdict_rows else None
    candidate = _latest_candidate(client, ticker)
    if sheet is None and not ctx["screens"] and chip is None \
            and candidate is None:
        return None

    print_ctx = cand_mod.print_classification(client, ticker)
    crossings = _crossings(client, ticker)

    know = None
    if sheet is not None:
        funds = sheet.get("fundamentals") or {}
        know = {
            "fact_sheet_id": sheet.get("id"),
            "status": sheet.get("status"), "tier": sheet.get("tier"),
            "price": sheet.get("price"),
            "price_as_of": sheet.get("price_as_of"),
            "price_vendor": sheet.get("price_vendor"),
            "band_basis": sheet.get("band_basis"),
            "anchor": sheet.get("anchor"), "bands": sheet.get("bands"),
            "peer": {"group": sheet.get("peer_group"),
                     "multiple": sheet.get("peer_multiple"),
                     "count": sheet.get("peer_count"),
                     "basis": sheet.get("peer_basis")},
            "guidance_percentile": sheet.get("guidance_percentile"),
            "gap_range_widths": sheet.get("gap_range_widths"),
            "directions": sheet.get("directions") or {},
            "fundamentals_present": {
                k: v for k, v in funds.items()
                if k != "missing" and isinstance(v, dict)},
            "fundamentals_missing": list(funds.get("missing") or []),
            "guard_rejections": sheet.get("guard_rejections") or [],
            "ingest_notes": sheet.get("ingest_notes") or [],
            "stale": bool(sheet.get("stale")),
            "stale_reasons": sheet.get("stale_reasons") or [],
            "computed_at": sheet.get("computed_at"),
            "snapshot_id": sheet.get("snapshot_id"),
        }

    from tradehub.valuation.band_crossing import ENTRY_ACTIONS

    graded = [r for r in crossings if r.get("action") in ENTRY_ACTIONS
              and r.get("score_20") is not None]
    falsifier = None
    falsifier_source = None
    if verdict_rows and verdict_rows[0].get("falsifier"):
        falsifier = verdict_rows[0]["falsifier"]
        falsifier_source = "verdict record"
    elif sheet is not None and sheet.get("falsifier"):
        falsifier = sheet["falsifier"]
        falsifier_source = "fact sheet"

    judgment = {
        "verdict": chip,
        "candidate": candidate,
        "falsifier": falsifier,
        "falsifier_source": falsifier_source,
        "crossings_graded": len(graded),
        "crossings_mean_score": (
            round(sum(float(r["score_20"]) for r in graded) / len(graded), 4)
            if graded else None),
    }

    missing: list[str] = []
    if sheet is None:
        missing.append("no guidance fact sheet on record")
    else:
        if sheet.get("status") != "banded":
            missing.append(_STATUS_GAPS.get(
                sheet.get("status"),
                f"no bands — sheet status {sheet.get('status')}"))
        if sheet.get("stale"):
            missing.append("fact sheet is stale — the zone is held and "
                           "no verdict renders on it")
        fund_missing = (sheet.get("fundamentals") or {}).get("missing") or []
        if fund_missing:
            missing.append("fundamentals not on file: "
                           + ", ".join(fund_missing))
    if not ctx["screens"]:
        missing.append("not a member of any recorded screen run")
    if print_ctx is None:
        missing.append("no print classification on record for this name")
    if chip is None:
        if candidate and candidate["state"] == "pending":
            missing.append(f"debate candidate queued "
                           f"({candidate['candidate_class']}) — no debate "
                           "verdict rendered yet")
        else:
            missing.append("no debate verdict rendered yet")

    return {
        "ticker": ticker,
        "snapshot": ({"id": snap.get("id"),
                      "computed_at": snap.get("computed_at"),
                      "completed_at": snap.get("completed_at")}
                     if snap else None),
        "know": know,
        "systems": {
            "zone": (sheet or {}).get("baseline_verdict"),
            "gap_range_widths": (sheet or {}).get("gap_range_widths"),
            "screens": ctx["screens"],
            "entrants": ctx["entrants"],
            "crossings": [{
                "id": r.get("id"), "book": r.get("book"),
                "zone": r.get("zone"), "action": r.get("action"),
                "score_20": r.get("score_20"),
                "created_at": r.get("created_at"),
                "snapshot_id": r.get("snapshot_id"),
            } for r in crossings],
            "print_classification": print_ctx,
        },
        "judgment": judgment,
        "missing": missing,
    }
