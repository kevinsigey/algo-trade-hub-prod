"""Supabase access for the valuation engine: read guidance_records, write and
read valuation_fact_sheets (append-only; latest row per ticker is current)."""
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
