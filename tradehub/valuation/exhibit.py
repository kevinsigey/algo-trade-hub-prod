"""Exhibit A: the fact sheet as the debate's fixed factual core (spec
section 4), plus the peer state frozen at render time (section 6: grading
joins exactly what the verdict saw, so each peer's price is captured on the
verdict record, never re-read later)."""
from __future__ import annotations

from tradehub.valuation import store as val_store


def exhibit_a(row: dict) -> dict:
    """The structured exhibit from a stored fact-sheet row."""
    fundamentals = {}
    for key, val in (row.get("fundamentals") or {}).items():
        if key == "missing":
            fundamentals["missing"] = list(val or [])
        elif isinstance(val, dict):
            fundamentals[key] = {"value": val.get("value"),
                                 "as_of": val.get("as_of")}
    return {
        "ticker": row["ticker"],
        "fact_sheet_id": row.get("id"),
        "computed_at": row.get("computed_at"),
        "status": row.get("status"),
        "tier": row.get("tier"),
        "price": row.get("price"),
        "price_as_of": row.get("price_as_of"),
        "band_basis": row.get("band_basis", "eps"),
        "anchor": row.get("anchor"),
        "bands": row.get("bands"),
        "implied": {"eps": row.get("implied_eps"),
                    "revenue": row.get("implied_revenue")},
        "gap_range_widths": row.get("gap_range_widths"),
        "guidance_percentile": row.get("guidance_percentile"),
        "baseline_verdict": row.get("baseline_verdict"),
        "peer": {"group": row.get("peer_group"),
                 "multiple": row.get("peer_multiple"),
                 "count": row.get("peer_count"),
                 "basis": row.get("peer_basis")},
        "directions": row.get("directions") or {},
        "fundamentals": fundamentals,
        "falsifier": row.get("falsifier"),
        "stale": bool(row.get("stale")),
    }


def _fmt(value, digits=2):
    if value is None:
        return "not on file"
    return f"{float(value):,.{digits}f}"


def render_markdown(ex: dict) -> str:
    """The exhibit as fixed text — injected verbatim into every stage of the
    forked debate, and shown on the verdict record."""
    anchor = ex.get("anchor") or {}
    bands = ex.get("bands") or {}
    peer = ex.get("peer") or {}
    lines = [f"# Exhibit A — {ex['ticker']} valuation fact sheet",
             f"Fact sheet #{ex.get('fact_sheet_id')} computed "
             f"{ex.get('computed_at')}; price {_fmt(ex.get('price'))} "
             f"as of {ex.get('price_as_of') or 'not on file'}.",
             "",
             "## The recorded guide",
             f"{anchor.get('metric') or 'guide'} for "
             f"{anchor.get('period') or 'the guided year'}: "
             f"{_fmt(anchor.get('low'))} to {_fmt(anchor.get('high'))} "
             f"(mid {_fmt(anchor.get('mid'))}); consensus "
             f"{_fmt(anchor.get('consensus'))}; recorded "
             f"{anchor.get('recorded_at') or 'not on file'} "
             f"(accession {anchor.get('accession') or 'not on file'})."]
    for metric, d in sorted((ex.get("directions") or {}).items()):
        lines.append(f"Guide direction ({metric}): {d.get('direction')} — "
                     f"latest mid {_fmt(d.get('mid'))} for {d.get('period')}.")
    lines += ["",
              "## Bands (guide x frozen peer multiple)",
              f"Peer group: {peer.get('group') or 'not on file'}; median "
              f"multiple {_fmt(peer.get('multiple'))} across "
              f"{peer.get('count') or 0} peers ({peer.get('basis')}).",
              f"Bear {_fmt(bands.get('bear'))} / Base {_fmt(bands.get('base'))}"
              f" / Bull {_fmt(bands.get('bull'))} "
              f"(band basis: {ex.get('band_basis')}).",
              f"Price {_fmt(ex.get('price'))} sits at gap "
              f"{ex.get('gap_range_widths')} guide-range widths from the "
              f"guide mid; guidance percentile "
              f"{ex.get('guidance_percentile')}.",
              f"Band-rule baseline verdict: {ex.get('baseline_verdict')}.",
              "",
              "## Fundamentals on file (EDGAR, as-of stamped)"]
    for key, val in sorted((ex.get("fundamentals") or {}).items()):
        if key == "missing":
            if val:
                lines.append(f"Missing: {', '.join(val)}.")
            continue
        lines.append(f"- {key}: {_fmt(val.get('value'))} "
                     f"(as of {val.get('as_of') or 'not on file'})")
    lines += ["", "## Falsifier", str(ex.get("falsifier") or "not recorded")]
    if ex.get("stale"):
        lines.append("\nSTALE: this sheet is past a staleness gate.")
    return "\n".join(lines)


def freeze_peer_states(row: dict, *, prices_fn) -> dict:
    """Freeze the peer group's state at render: every member's last price.
    prices_fn(members) -> {ticker: (price, price_as_of)}. Members without a
    price are recorded with price None — absence is data, never invented."""
    enriched = val_store.with_peer_members(row)
    members = enriched.get("peer_members") or []
    prices = prices_fn(members) if members else {}
    frozen_members = []
    for member in members:
        hit = prices.get(member)
        frozen_members.append({
            "ticker": member,
            "price": hit[0] if hit else None,
            "price_as_of": hit[1] if hit else None,
        })
    return {
        "group": row.get("peer_group"),
        "basis": row.get("peer_basis"),
        "multiple": row.get("peer_multiple"),
        "count": row.get("peer_count"),
        "members": frozen_members,
    }
