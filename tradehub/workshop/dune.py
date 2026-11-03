"""Dune Analytics as a Workshop data source (crypto step 3, Kevin, 2026-11-03):
on-chain ideas testing. A rule condition with source "dune" reads a named
series from the dune_series cache table -- points a refresh job copied out
of Kevin's own Dune queries (his credential lives in his connector vault,
so the hub never calls Dune itself). The engine treats the series like
FRED: daily values, t-2 publication lag, the standard measures.

A key with no cached points refuses the run (UnknownSymbol) rather than
silently reading as zero -- the hub's connected-but-empty rule.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

TABLE = "dune_series"


def _client(supa):
    if supa is not None:
        return supa
    from tradehub.core.supabase_client import get_client

    return get_client()


def dune_series(key: str, start: date, *, supa=None) -> pd.Series:
    """The cached points for `key` on/after `start`, as a daily series."""
    from tradehub.workshop.data import UnknownSymbol

    rows = _client(supa).table(TABLE).select("points").eq("key", key).execute().data
    if not rows:
        raise UnknownSymbol(f"no Dune series is cached under {key} -- refresh it before running this idea")
    points = [(str(p.get("date"))[:10], p.get("value")) for p in (rows[0].get("points") or [])]
    dated = sorted((d, float(v)) for d, v in points if v is not None and d >= start.isoformat())
    if not dated:
        raise UnknownSymbol(f"the Dune series {key} has no points on or after {start.isoformat()} -- "
                            "refresh it or start the idea earlier")
    idx = pd.DatetimeIndex([d for d, _ in dated])
    return pd.Series([v for _, v in dated], index=idx, name=key, dtype=float)


def list_dune_series(*, supa=None) -> list[dict]:
    """The catalogue: what a rule can read, and how fresh it is."""
    rows = _client(supa).table(TABLE).select("key,query_id,value_column,points,updated_at").execute().data or []
    out = []
    for r in rows:
        points = r.get("points") or []
        days = sorted(str(p.get("date"))[:10] for p in points if p.get("date"))
        out.append({"key": r["key"], "query_id": r.get("query_id"), "value_column": r.get("value_column"),
                    "n_points": len(points), "first_date": days[0] if days else None,
                    "last_date": days[-1] if days else None, "updated_at": r.get("updated_at")})
    return sorted(out, key=lambda r: r["key"])
