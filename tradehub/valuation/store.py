"""Supabase access for the valuation engine: read guidance_records, write and
read valuation_fact_sheets (append-only; latest row per ticker is current).

Snapshot integrity (reliability pass, 2026-11-09): a full compute opens a
valuation_snapshots row, stamps every sheet it writes, and completes the
snapshot when the last sheet lands. The Guidance read path serves ONLY the
latest completed snapshot -- a recompute in flight never changes what is
served; it publishes a new snapshot whole (scar tissue #9: an unversioned
latest-per-ticker mix diverged silently between page loads while the
fleet ingested). valuation_band_history carries the per-name band record
of each snapshot for the crossings scanner / grading / band alerts."""
from __future__ import annotations

RECORD_COLS = ("ticker,metric,period,unit,low,high,consensus,"
               "consensus_period,consensus_source,accession,created_at")


def guided_tickers(client) -> list[str]:
    rows = (client.table("guidance_records").select("ticker")
            .execute().data) or []
    return sorted({r["ticker"] for r in rows if r.get("ticker")})


def records_for(client, ticker: str) -> list[dict]:
    return (client.table("guidance_records").select(RECORD_COLS)
            .eq("ticker", ticker).order("created_at").execute().data) or []


def all_records(client) -> dict[str, list[dict]]:
    rows = (client.table("guidance_records").select(RECORD_COLS)
            .order("created_at").execute().data) or []
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["ticker"], []).append(r)
    return out


def insert_sheet(client, sheet: dict) -> None:
    row = {
        "ticker": sheet["ticker"],
        "tier": sheet.get("tier", "open"),
        "status": sheet["status"],
        "price": sheet.get("price"),
        "price_as_of": sheet.get("price_as_of"),
        "peer_group": sheet.get("peer_group"),
        "peer_multiple": sheet.get("peer_multiple"),
        "peer_count": sheet.get("peer_count"),
        "peer_basis": sheet.get("peer_basis"),
        "anchor": sheet.get("anchor"),
        "bands": sheet.get("bands"),
        "implied_eps": (sheet.get("implied") or {}).get("eps"),
        "implied_revenue": (sheet.get("implied") or {}).get("revenue"),
        "band_basis": sheet.get("band_basis", "eps"),
        "gap_range_widths": sheet.get("gap_range_widths"),
        "guidance_percentile": sheet.get("guidance_percentile"),
        "baseline_verdict": sheet.get("baseline_verdict"),
        "stale": bool(sheet.get("stale")),
        "falsifier": sheet.get("falsifier"),
        "directions": sheet.get("directions"),
        "fundamentals": sheet.get("fundamentals"),
        "inputs": sheet.get("inputs"),
        "snapshot_id": sheet.get("snapshot_id"),
        "guard_rejections": sheet.get("guard_rejections") or [],
        "stale_reasons": sheet.get("stale_reasons") or [],
        "ingest_notes": sheet.get("ingest_notes") or [],
        "price_vendor": sheet.get("price_vendor"),
    }
    client.table("valuation_fact_sheets").insert(row).execute()


def latest_sheets(client) -> list[dict]:
    rows = (client.table("valuation_fact_sheets").select("*")
            .order("computed_at", desc=True).execute().data) or []
    seen: dict[str, dict] = {}
    for r in rows:
        seen.setdefault(r["ticker"], r)
    return [seen[t] for t in sorted(seen)]


def latest_sheet(client, ticker: str) -> dict | None:
    rows = (client.table("valuation_fact_sheets").select("*")
            .eq("ticker", ticker).order("computed_at", desc=True)
            .limit(1).execute().data) or []
    return rows[0] if rows else None


# ── snapshots ────────────────────────────────────────────────────────────────

def _iso(value) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else value


def begin_snapshot(client, computed_at, *, source: str = "valuation_run"):
    """Open a snapshot for a full compute; returns its id, or None when the
    snapshots table is unreachable (pre-migration) -- the compute then runs
    unstamped, exactly the legacy behavior, rather than failing."""
    try:
        rows = (client.table("valuation_snapshots")
                .insert({"computed_at": _iso(computed_at), "source": source})
                .execute().data) or []
        return rows[0]["id"] if rows else None
    except Exception:  # noqa: BLE001 -- pre-migration: unstamped compute
        return None


def complete_snapshot(client, snapshot_id, *, sheet_count: int,
                      banded_count: int, completed_at=None) -> None:
    if snapshot_id is None:
        return
    if completed_at is None:
        from datetime import datetime, timezone

        completed_at = datetime.now(timezone.utc)
    (client.table("valuation_snapshots")
     .update({"completed_at": _iso(completed_at), "sheet_count": sheet_count,
              "banded_count": banded_count})
     .eq("id", snapshot_id).execute())


def latest_snapshot(client) -> dict | None:
    """The newest COMPLETED snapshot, or None. An in-flight recompute is
    invisible here by construction -- that is the F1 fix."""
    try:
        rows = (client.table("valuation_snapshots").select("*")
                .order("id", desc=True).limit(10).execute().data) or []
    except Exception:  # noqa: BLE001 -- pre-migration reads as no snapshot
        return None
    for row in rows:
        if row.get("completed_at"):
            return row
    return None


def snapshot_sheets(client, snapshot_id) -> list[dict]:
    rows = (client.table("valuation_fact_sheets").select("*")
            .eq("snapshot_id", snapshot_id).execute().data) or []
    return sorted(rows, key=lambda r: r.get("ticker") or "")


def latest_snapshot_sheets(client) -> tuple[dict | None, list[dict]]:
    """(snapshot, its sheets) for the latest completed snapshot. Falls back
    to the legacy latest-per-ticker read with snapshot None when no
    snapshot has completed yet (pre-fix data) -- the caller stamps that
    state honestly instead of inventing a version."""
    snap = latest_snapshot(client)
    if snap is None:
        return None, latest_sheets(client)
    return snap, snapshot_sheets(client, snap["id"])


def snapshot_sheet(client, snapshot_id, ticker: str) -> dict | None:
    rows = (client.table("valuation_fact_sheets").select("*")
            .eq("snapshot_id", snapshot_id).eq("ticker", ticker)
            .execute().data) or []
    return rows[0] if rows else None


# ── band history ─────────────────────────────────────────────────────────────

def history_row(sheet: dict, *, snapshot_id, computed_at) -> dict:
    """The per-name band record of one snapshot (F2, compact by Kevin's
    2026-11-09 design directive): only what grading a crossing or
    reconstructing the page needs -- guide low/high + unit, the anchor's
    direction, the multiple, the bands, the price, the zone. Peer detail
    and reasons live on the fact sheet (current state), never per
    snapshot; the gap recomputes from these fields at read time."""
    anchor = sheet.get("anchor") or {}
    bands = sheet.get("bands") or {}
    metric = anchor.get("metric")
    direction = None
    if metric:
        direction = ((sheet.get("directions") or {}).get(metric)
                     or {}).get("direction")
    return {
        "snapshot_id": snapshot_id,
        "ticker": sheet.get("ticker"),
        "band_basis": sheet.get("band_basis"),
        "guide_metric": metric,
        "guide_unit": ("usd" if metric == "revenue"
                       else "usd_per_share" if metric else None),
        "guide_low": anchor.get("low"),
        "guide_high": anchor.get("high"),
        "direction": direction,
        "peer_multiple": sheet.get("peer_multiple"),
        "bear": bands.get("bear"),
        "base": bands.get("base"),
        "bull": bands.get("bull"),
        "price": sheet.get("price"),
        "zone": sheet.get("baseline_verdict"),
        "computed_at": _iso(computed_at),
    }


def insert_history(client, rows: list[dict]) -> None:
    if rows:
        client.table("valuation_band_history").insert(rows).execute()


def snapshot_history(client, snapshot_id) -> list[dict]:
    rows = (client.table("valuation_band_history").select("*")
            .eq("snapshot_id", snapshot_id).execute().data) or []
    return sorted(rows, key=lambda r: r.get("ticker") or "")


def latest_snapshot_history(client) -> list[dict]:
    snap = latest_snapshot(client)
    if snap is None:
        return []
    return snapshot_history(client, snap["id"])


def with_peer_members(row: dict) -> dict:
    """Read-side detail enrichment: the frozen peer group's member tickers,
    derived from the same frozen map the engine used (tradehub.valuation.
    peers) -- never stored on the sheet, so the list endpoint stays the
    stored rows verbatim. A 'sector:<name>' group resolves to that sector's
    members; anything unknown resolves to an empty list rather than a guess.
    `peer_count` on the sheet remains the count that actually contributed a
    usable multiple, which can be smaller than the group's membership."""
    from tradehub.valuation import peers

    out = dict(row)
    group = row.get("peer_group")
    members: list[str] = []
    if group:
        if group.startswith("sector:"):
            members = peers.sector_members(group[len("sector:"):])
        else:
            members = peers.group_members(group)
    out["peer_members"] = members
    return out
