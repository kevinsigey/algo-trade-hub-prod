"""The Guidance page's stamped summary block (re-presentation build).

ONE additive block on the /api/valuation-bands payload, computed only
from data the hub already persists -- no new ingest, no scanner/watcher/
queue changes:

- counts for the verdict strip, from `valuation_band_history` rows of
  the latest COMPLETED snapshot (one compact row per name per snapshot);
- the needs-attention feed: a diff of the latest vs the previous
  COMPLETED snapshot's history (zone changes, guide revisions under
  latest-filing-wins, newly banded names), plus the crossings stamped
  with the latest snapshot id, with conjunctions (strong zone x fresh
  print classification x recorded screen membership) pinned on top;
- the classified-names list from `forward_file_classifications`
  (latest row per ticker wins, the readers' own rule);
- the pending debate count from the persisted candidate queue;
- the held map for board markers, through the candidates module's
  existing held computation (display context only).

Scar tissue #9: everything here derives from COMPLETED snapshots and
carries their ids. When there is no previous snapshot the feed says so
(`no_previous_snapshot`) instead of calling every name new; when the
diff is empty the feed is empty and the page renders the honest
"nothing changed" state -- items are never invented to fill the feed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tradehub.valuation import candidates as cand
from tradehub.valuation import store as val_store

STRONG_ZONES = cand.STRONG_ZONES
_EPS = 1e-9

# Round 6 accounting: a filtered view must account for every name its
# count promises. A classified or held name that is not on the board
# carries the reason it is not banded, read from its stored sheet.
NO_SHEET_REASON = ("not in the guidance universe / "
                   "no fact sheet in this snapshot")
_NOT_BANDED_REASONS = {
    "no_full_year_guide": "no full-year guide on file — no bands computed",
    "guide_rejected": "guide rejected by the sheet guards — no bands computed",
    "no_peer_multiple": "no peer multiple — no bands computed",
}


def _sheet_account(sheet: dict | None) -> tuple[bool, str | None, str | None]:
    """(banded, sheet_status, reason) for one name, from its stored
    sheet in the snapshot (sheet None when the name has no sheet there).
    Banded is the board's own test — the sheet's status — so the
    accounting reconciles with the board the page renders."""
    if sheet is None:
        return False, None, NO_SHEET_REASON
    status = sheet.get("status")
    if status == "banded":
        return True, status, None
    reason = _NOT_BANDED_REASONS.get(status)
    if reason is None:
        reason = (f"sheet status {status} — no bands computed" if status
                  else NO_SHEET_REASON)
    return False, status, reason


def previous_snapshot(client) -> dict | None:
    """The second-newest COMPLETED snapshot, or None. An in-flight
    recompute is invisible here, exactly as in store.latest_snapshot."""
    try:
        rows = (client.table("valuation_snapshots").select("*")
                .order("id", desc=True).limit(10).execute().data) or []
    except Exception:  # noqa: BLE001 -- pre-migration reads as no snapshot
        return None
    completed = [r for r in rows if r.get("completed_at")]
    return completed[1] if len(completed) > 1 else None


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _banded(row: dict) -> bool:
    return row.get("bear") is not None


def _bands(row: dict) -> dict | None:
    if not _banded(row):
        return None
    return {"bear": _num(row.get("bear")), "base": _num(row.get("base")),
            "bull": _num(row.get("bull"))}


def diff_history(latest: list[dict], prev: list[dict]) -> dict:
    """Zone changes, guide revisions, and newly banded names between two
    snapshots' band-history rows. Pure function of the stored rows.

    A name that left coverage is not an item (its absence is a coverage
    fact the reference table shows, not a change to act on). With no
    previous snapshot there is nothing to diff against -- the caller
    marks the feed unavailable rather than calling every name new."""
    out = {"zone_changes": [], "guide_revisions": [], "new_banded": []}
    if not prev:
        return out
    before = {r.get("ticker"): r for r in prev if r.get("ticker")}
    for row in latest:
        ticker = row.get("ticker")
        if not ticker:
            continue
        old = before.get(ticker)
        bands = _bands(row)
        if _banded(row) and (old is None or not _banded(old)):
            out["new_banded"].append({
                "ticker": ticker, "zone": row.get("zone"),
                "bands": bands, "price": _num(row.get("price"))})
            continue
        if old is None:
            continue
        if _banded(row) and _banded(old) \
                and row.get("zone") != old.get("zone"):
            out["zone_changes"].append({
                "ticker": ticker, "from_zone": old.get("zone"),
                "to_zone": row.get("zone"), "bands": bands,
                "price": _num(row.get("price"))})
        lo, hi = _num(row.get("guide_low")), _num(row.get("guide_high"))
        olo, ohi = _num(old.get("guide_low")), _num(old.get("guide_high"))
        if None not in (lo, hi, olo, ohi) \
                and (abs(lo - olo) > _EPS or abs(hi - ohi) > _EPS):
            out["guide_revisions"].append({
                "ticker": ticker, "metric": row.get("guide_metric"),
                "from_low": olo, "from_high": ohi,
                "to_low": lo, "to_high": hi,
                "direction": row.get("direction"),
                "bands": bands, "price": _num(row.get("price"))})
    return out


def _classifications(client) -> list[dict]:
    """Latest classification per ticker (the readers' rule: newest
    as_of wins), sorted by ticker. Missing table reads as empty."""
    try:
        rows = (client.table("forward_file_classifications")
                .select("*").execute().data) or []
    except Exception:  # noqa: BLE001 -- no store yet is an honest empty
        return []
    latest: dict[str, dict] = {}
    for row in rows:
        ticker = row.get("ticker")
        if not ticker or row.get("classification") not in (
                "improved", "intact", "deteriorated"):
            continue
        cur = latest.get(ticker)
        if cur is None or str(row.get("as_of") or "") >= str(cur.get("as_of") or ""):
            latest[ticker] = row
    return [{"ticker": t, "classification": latest[t]["classification"],
             "as_of": latest[t].get("as_of")} for t in sorted(latest)]


def _crossings(client, snapshot_id) -> list[dict]:
    """Crossing rows stamped with this snapshot id (F4 provenance),
    newest first. The scanner is untouched; this only reads its log."""
    try:
        rows = (client.table("band_crossings").select("*")
                .eq("snapshot_id", snapshot_id)
                .order("id", desc=True).limit(50).execute().data) or []
    except Exception:  # noqa: BLE001 -- pre-migration reads as no crossings
        return []
    return [{"ticker": r.get("ticker"), "book": r.get("book"),
             "zone": r.get("zone"), "action": r.get("action"),
             "created_at": r.get("created_at"),
             "bands": ({"bear": _num(r.get("bear")),
                        "base": _num(r.get("base")),
                        "bull": _num(r.get("bull"))}
                       if r.get("bear") is not None else None),
             "price": _num(r.get("price"))} for r in rows]


def _conjunctions(client, latest_hist: list[dict], *, now: datetime,
                  classified: dict[str, dict]) -> list[dict]:
    """Strong zone x fresh print classification (<= PRINT_RECENT_DAYS,
    the candidates module's own window) x recorded screen membership.
    Reuses candidates.screen_contexts -- recorded runs only, never
    ad-hoc builder state."""
    strong = {r["ticker"]: r for r in latest_hist
              if r.get("zone") in STRONG_ZONES and r.get("ticker")}
    if not strong:
        return []
    try:
        contexts = cand.screen_contexts(client, now=now)
    except Exception:  # noqa: BLE001 -- no screen context: no conjunctions
        return []
    out = []
    for ticker in sorted(strong):
        cls = classified.get(ticker)
        if cls is None:
            continue
        day = cand._parse_day(cls.get("as_of"))
        if day is None or (now.date() - day).days > cand.PRINT_RECENT_DAYS:
            continue
        ctx = contexts.get(ticker) or {}
        if not ctx.get("survivor"):
            continue
        screens = [s.get("screen_name") for s in ctx.get("screens") or []
                   if s.get("screen_name")]
        row = strong[ticker]
        out.append({"ticker": ticker, "zone": row.get("zone"),
                    "classification": cls["classification"],
                    "as_of": cls.get("as_of"), "screens": screens,
                    "bands": _bands(row), "price": _num(row.get("price"))})
    return out


def build_summary(client, *, positions_fn=None,
                  now: datetime | None = None) -> dict:
    """Assemble the page summary for the latest completed snapshot."""
    now = now or datetime.now(timezone.utc)
    empty_counts = {"banded": 0, "buy_zones": 0, "strong_short_zones": 0,
                    "crossings_since_last_snapshot": 0,
                    "pending_debates": 0, "classified_prints": 0}
    snap = val_store.latest_snapshot(client)
    if snap is None:
        return {"snapshot_id": None, "previous_snapshot_id": None,
                "counts": empty_counts, "feed_state": "no_snapshot",
                "feed": [], "classified_names": [], "crossings": [],
                "held": {}, "held_names": [],
                "held_positions_unavailable": False}
    snapshot_id = snap["id"]
    prev = previous_snapshot(client)
    latest_hist = val_store.snapshot_history(client, snapshot_id)
    sheet_by = {s["ticker"]: s
                for s in val_store.snapshot_sheets(client, snapshot_id)
                if s.get("ticker")}
    prev_hist = (val_store.snapshot_history(client, prev["id"])
                 if prev else [])
    banded_rows = [r for r in latest_hist if _banded(r)]
    counts = {
        "banded": len(banded_rows),
        "buy_zones": sum(1 for r in banded_rows
                         if r.get("zone") in ("buy_zone", "buy_zone_strong")),
        "strong_short_zones": sum(1 for r in banded_rows
                                  if r.get("zone") == "short_zone_strong"),
        "crossings_since_last_snapshot": 0,
        "pending_debates": 0,
        "classified_prints": 0,
    }
    crossings = _crossings(client, snapshot_id)
    counts["crossings_since_last_snapshot"] = len(crossings)
    try:
        queue = cand.candidates_for_snapshot(client, snapshot_id)
        counts["pending_debates"] = sum(
            1 for r in queue if r.get("state") == "pending")
    except Exception:  # noqa: BLE001 -- queue unreadable reads as zero here;
        counts["pending_debates"] = 0  # the DebateQueue panel shows its own
    classified_list = _classifications(client)
    counts["classified_prints"] = len(classified_list)
    classified = {c["ticker"]: c for c in classified_list}
    held = cand.held_positions(client, positions_fn)
    # Round 6 accounting (additive): every classified and every held
    # name carries its board standing — banded, or the stored sheet
    # status that says why not — so the page's filtered views reconcile
    # with the counts they promise instead of silently dropping names.
    for entry in classified_list:
        banded, status, reason = _sheet_account(
            sheet_by.get(entry["ticker"]))
        entry.update({"banded": banded, "sheet_status": status,
                      "reason": reason})
    held_names = []
    for ticker in sorted(held or {}):
        banded, status, reason = _sheet_account(sheet_by.get(ticker))
        held_names.append({"ticker": ticker,
                           "books": held[ticker].get("books", []),
                           "qty": held[ticker].get("qty"),
                           "sleeves": held[ticker].get("sleeves", []),
                           "banded": banded, "sheet_status": status,
                           "reason": reason})
    # ── the feed: conjunctions pinned, then crossings, then the diff ──
    feed: list[dict] = []
    for item in _conjunctions(client, latest_hist, now=now,
                              classified=classified):
        feed.append({"kind": "conjunction", **item})
    for row in crossings:
        feed.append({"kind": "crossing", **row})
    if prev is not None:
        diff = diff_history(latest_hist, prev_hist)
        for item in diff["zone_changes"]:
            feed.append({"kind": "zone_change", **item})
        for item in diff["guide_revisions"]:
            feed.append({"kind": "guide_revision", **item})
        for item in diff["new_banded"]:
            feed.append({"kind": "new_banded", **item})
        feed_state = "ok"
    else:
        feed_state = "no_previous_snapshot"
    return {"snapshot_id": snapshot_id,
            "previous_snapshot_id": prev["id"] if prev else None,
            "counts": counts, "feed_state": feed_state, "feed": feed,
            "classified_names": classified_list, "crossings": crossings,
            "held": held or {}, "held_names": held_names,
            "held_positions_unavailable": held is None}
