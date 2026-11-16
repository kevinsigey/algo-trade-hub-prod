"""The Guidance page rebuild's board block (Kevin-approved brief,
2026-11-16): movers first, then the football-field grid, then the
missing-band queue — computed from the two latest COMPLETED snapshots
plus the guidance recorder, served as one additive block on
/api/valuation-bands. Read-path only: no ingest, no compute, no writes.

- MOVERS: guide revisions between the snapshots (the anchor metric's
  guide, from band history) ranked beside the recorder's capex and FCF
  guide revisions (the screening layer's own definition: a period's two
  most recent guide midpoints, the period whose latest guide is
  newest), and band migrations (zone changes). Held names pin first in
  every list.
- GRID: every banded name of the latest snapshot with its bands, the
  snapshot price (labelled with the snapshot's computed-at — never a
  live price in disguise), the position status computed from price vs
  bands, and the distance to the buy zone as the headline number.
  Market cap is price x diluted shares from the sheet's fundamentals,
  labelled as that derivation.
- MISSING-BAND QUEUE: held or classified (watched) names with no band
  in the latest snapshot, each with the stored reason it is not banded
  (the page_summary accounting) — a worklist, not a footnote.
- FRESHNESS: the snapshot's stamps and age ride on the block so the
  header can badge staleness against the stated cadence.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradehub.valuation import candidates as cand
from tradehub.valuation import page_summary
from tradehub.valuation import store as val_store

_EPS = 1e-9
CADENCE = ("Snapshots recompute hourly while the market is open, "
           "weekdays (valuation watch run)")
STALE_AFTER_HOURS = 30.0


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── guide revisions from the recorder (the screening definition) ────────────

def guide_change_pct(records: list[dict]) -> float | None:
    """% change between a period's two most recent guide midpoints, for
    the period whose latest guide is newest — the same rule the
    screening layer's capex/fcf guide-change fields use. None when no
    period has a comparable pair."""
    by_period: dict[str, list[dict]] = {}
    for r in records:
        if r.get("low") is None or r.get("high") is None \
                or not r.get("period"):
            continue
        by_period.setdefault(r["period"], []).append(r)
    best = None
    for rs in by_period.values():
        rs = sorted(rs, key=lambda r: str(r.get("created_at") or ""))
        if len(rs) < 2:
            continue
        prev_mid = (float(rs[-2]["low"]) + float(rs[-2]["high"])) / 2
        last_mid = (float(rs[-1]["low"]) + float(rs[-1]["high"])) / 2
        if not prev_mid:
            continue
        change = (last_mid - prev_mid) / abs(prev_mid) * 100
        if best is None or str(rs[-1].get("created_at") or "") > best[0]:
            best = (str(rs[-1].get("created_at") or ""), change)
    return None if best is None else best[1]


def _records(client) -> dict[str, list[dict]]:
    """Guidance records grouped by ticker, WITH the evidence column
    (val_store's RECORD_COLS omits it; the FCF rule needs it)."""
    rows = (client.table("guidance_records")
            .select("ticker,metric,period,low,high,evidence,created_at")
            .order("created_at").execute().data) or []
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["ticker"], []).append(r)
    return out


def recorder_revisions(records_by_ticker: dict[str, list[dict]]) -> dict:
    """{ticker: {"capex": pct|None, "fcf": pct|None}} from guidance
    records: capex reads metric 'capex'; FCF reads metric 'other' whose
    evidence names free cash flow (the recorder's convention)."""
    out: dict[str, dict] = {}
    for ticker, recs in records_by_ticker.items():
        capex = guide_change_pct(
            [r for r in recs if r.get("metric") == "capex"])
        fcf = guide_change_pct(
            [r for r in recs if r.get("metric") == "other"
             and "free cash flow" in (r.get("evidence") or "").lower()])
        if capex is not None or fcf is not None:
            out[ticker] = {"capex": capex, "fcf": fcf}
    return out


# ── grid position ────────────────────────────────────────────────────────────

def position(price, bands: dict | None) -> dict:
    """{status, distance_pct} for a price against a band set. Status:
    no_band / below_bear / buy_zone / between / above_bull (price at or
    below base is the buy zone; at or below bear is flagged separately
    as the deeper zone). distance_pct is the % the price sits above the
    base band (negative inside the zone) — the grid's headline number.
    """
    p = _num(price)
    if bands is None or p is None:
        return {"status": "no_band", "distance_pct": None}
    bear, base, bull = (_num(bands.get("bear")), _num(bands.get("base")),
                        _num(bands.get("bull")))
    if bear is None or base is None or bull is None or p == 0:
        return {"status": "no_band", "distance_pct": None}
    if p <= bear:
        status = "below_bear"
    elif p <= base:
        status = "buy_zone"
    elif p <= bull:
        status = "between"
    else:
        status = "above_bull"
    return {"status": status,
            "distance_pct": round((p - base) / p * 100, 2)}


def _bands_of(row: dict) -> dict | None:
    if row.get("bear") is None:
        return None
    return {"bear": _num(row.get("bear")), "base": _num(row.get("base")),
            "bull": _num(row.get("bull"))}


# ── assembly ─────────────────────────────────────────────────────────────────

def build_board(client, *, positions_fn=None,
                now: datetime | None = None) -> dict:
    """The board block for the latest completed snapshot. Sections fail
    soft independently; with no completed snapshot the block says so."""
    now = now or datetime.now(timezone.utc)
    empty = {"snapshot_id": None, "previous_snapshot_id": None,
             "freshness": None, "movers": None, "grid": [],
             "missing_band": []}
    snap = val_store.latest_snapshot(client)
    if snap is None:
        return empty
    prev = page_summary.previous_snapshot(client)
    snapshot_id = snap["id"]
    sheets = val_store.snapshot_sheets(client, snapshot_id)
    sheet_by = {s["ticker"]: s for s in sheets if s.get("ticker")}
    latest_hist = val_store.snapshot_history(client, snapshot_id)
    prev_hist = (val_store.snapshot_history(client, prev["id"])
                 if prev else [])
    held = cand.held_positions(client, positions_fn) or {}
    held_set = set(held)

    computed_at = snap.get("computed_at")
    age_hours = None
    if computed_at:
        parsed = _parse(computed_at)
        if parsed is not None:
            age_hours = round((now - parsed).total_seconds() / 3600, 2)
    freshness = {"snapshot_id": snapshot_id,
                 "computed_at": computed_at,
                 "completed_at": snap.get("completed_at"),
                 "age_hours": age_hours,
                 "stale": (age_hours is not None
                           and age_hours > STALE_AFTER_HOURS),
                 "cadence": CADENCE,
                 "previous_snapshot_id": prev["id"] if prev else None,
                 "previous_computed_at": (prev.get("computed_at")
                                          if prev else None)}

    movers = _movers(client, latest_hist, prev_hist, held_set,
                     have_prev=prev is not None)
    grid = _grid(sheets, latest_hist, held)
    missing = _missing_band(client, sheet_by, held)
    return {"snapshot_id": snapshot_id,
            "previous_snapshot_id": prev["id"] if prev else None,
            "freshness": freshness, "movers": movers, "grid": grid,
            "missing_band": missing}


def _parse(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(
            tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _movers(client, latest_hist, prev_hist, held_set, *,
            have_prev: bool) -> dict | None:
    """The movers block, or None when there is no previous snapshot to
    move against (the page renders the honest no-baseline state)."""
    if not have_prev:
        return None
    diff = page_summary.diff_history(latest_hist, prev_hist)
    revisions: list[dict] = []
    for item in diff["guide_revisions"]:
        lo, hi = item["from_low"], item["from_high"]
        nlo, nhi = item["to_low"], item["to_high"]
        mid_old, mid_new = (lo + hi) / 2, (nlo + nhi) / 2
        change = (round((mid_new - mid_old) / abs(mid_old) * 100, 2)
                  if mid_old else None)
        revisions.append({"ticker": item["ticker"], "metric": "anchor",
                          "guide_metric": item.get("metric"),
                          "change_pct": change,
                          "from": [lo, hi], "to": [nlo, nhi],
                          "direction": item.get("direction"),
                          "held": item["ticker"] in held_set})
    try:
        records = _records(client)
    except Exception:  # noqa: BLE001 -- recorder unreadable: anchor only
        records = {}
    for ticker, rev in recorder_revisions(records).items():
        for metric in ("capex", "fcf"):
            if rev.get(metric) is not None:
                revisions.append({
                    "ticker": ticker, "metric": metric,
                    "guide_metric": metric,
                    "change_pct": round(rev[metric], 2),
                    "from": None, "to": None, "direction": None,
                    "held": ticker in held_set})
    revisions.sort(key=lambda r: (not r["held"],
                                  -(abs(r["change_pct"])
                                    if r["change_pct"] is not None
                                    else -1)))
    migrations = [{"ticker": z["ticker"], "from_zone": z["from_zone"],
                   "to_zone": z["to_zone"], "price": z["price"],
                   "bands": z["bands"],
                   "held": z["ticker"] in held_set}
                  for z in diff["zone_changes"]]
    migrations.sort(key=lambda m: not m["held"])
    held_status = []
    latest_by = {r.get("ticker"): r for r in latest_hist if r.get("ticker")}
    for ticker in sorted(held_set):
        row = latest_by.get(ticker)
        if row is None:
            continue
        bands = _bands_of(row)
        pos = position(row.get("price"), bands)
        held_status.append({"ticker": ticker, "zone": row.get("zone"),
                            "status": pos["status"],
                            "distance_pct": pos["distance_pct"],
                            "price": _num(row.get("price")),
                            "bands": bands})
    return {"guide_revisions": revisions, "band_migrations": migrations,
            "held_status": held_status,
            "snapshot_pair": True}


def _grid(sheets, latest_hist, held) -> list[dict]:
    hist_by = {r.get("ticker"): r for r in latest_hist if r.get("ticker")}
    rows: list[dict] = []
    for sheet in sheets:
        if sheet.get("status") != "banded" or not sheet.get("bands"):
            continue
        ticker = sheet["ticker"]
        bands = sheet["bands"]
        price = _num(sheet.get("price"))
        pos = position(price, bands)
        shares = ((sheet.get("fundamentals") or {}).get("shares_diluted")
                  or {})
        shares_val = _num(shares.get("value")) if isinstance(
            shares, dict) else None
        market_cap = (round(price * shares_val, 2)
                      if price is not None and shares_val else None)
        rows.append({
            "ticker": ticker,
            "bands": {"bear": _num(bands.get("bear")),
                      "base": _num(bands.get("base")),
                      "bull": _num(bands.get("bull"))},
            "price": price,
            "price_as_of": sheet.get("price_as_of"),
            "status": pos["status"],
            "distance_pct": pos["distance_pct"],
            "held": ticker in held,
            "books": (held.get(ticker) or {}).get("books", []),
            "market_cap": market_cap,
            "zone": (hist_by.get(ticker) or {}).get("zone"),
        })
    rows.sort(key=lambda r: (not r["held"],
                             r["distance_pct"] if r["distance_pct"]
                             is not None else 1e9))
    return rows


def _missing_band(client, sheet_by, held) -> list[dict]:
    """Held or classified names with no band in the latest snapshot,
    each with the stored reason (page_summary's accounting)."""
    classified = {c["ticker"] for c in page_summary._classifications(client)}
    out: list[dict] = []
    for ticker in sorted(set(held) | classified):
        banded, status, reason = page_summary._sheet_account(
            sheet_by.get(ticker))
        if banded:
            continue
        out.append({"ticker": ticker, "held": ticker in held,
                    "watched": ticker in classified,
                    "books": (held.get(ticker) or {}).get("books", []),
                    "sheet_status": status, "reason": reason})
    out.sort(key=lambda r: (not r["held"], r["ticker"]))
    return out
