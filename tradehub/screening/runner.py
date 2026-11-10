"""Executes a validated query spec against the data layer.

Output: a tidy table (ticker + every field the spec used + composite score)
and a provenance footer: per-column source + as-of, the missing-field ledger
for the fields used, context values, and the echoed spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .functions import REGISTRY
from .sources import DataStore
from .spec import validate_spec
from .universes import issuer_key, resolve_universe

import os

# Interactive runs enrich one ticker at a time from rate-limited free sources;
# the cap keeps a run inside a sane budget and is DISCLOSED in the footer when
# it bites (the prototype's rule: caps on the run line, never silent).
MAX_UNIVERSE = int(os.environ.get("TRADEHUB_SCREENING_MAX_UNIVERSE", "300"))

_SOURCE_KIND = {"yfinance prices": "prices", "yfinance.info": "info",
                "yfinance statements": "statements", "SEC EDGAR": "edgar",
                "FRED": "fred", "local": "local", "yfinance earnings": "earnings",
                "yfinance options": "options"}


def _col_name(call: dict) -> str:
    params = call.get("params") or {}
    if not params:
        return call["fn"]
    inner = ",".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{call['fn']}({inner})"


def _apply_op(col: pd.Series, op: str, value) -> pd.Series:
    if op == "lt":
        return col < value
    if op == "le":
        return col <= value
    if op == "gt":
        return col > value
    if op == "ge":
        return col >= value
    if op == "eq":
        return col == value
    if op == "ne":
        return col != value
    if op == "between":
        return (col >= value[0]) & (col <= value[1])
    if op == "in":
        return col.isin(value)
    if op in ("pct_gte", "pct_lte"):
        pct = col.rank(pct=True) * 100.0
        return pct >= value if op == "pct_gte" else pct <= value
    raise ValueError(f"unknown op {op}")


_KIND_OF_SOURCE_PREFIX = (("yfinance.info", "info"), ("yfinance statements", "statements"),
                          ("yfinance earnings", "earnings"), ("yfinance options", "options"))


def needed_kinds(spec: dict) -> set[str]:
    """The per-ticker data kinds a spec's fields will pull, from the registry's
    declared sources. Bulk or local sources (prices, EDGAR, FRED, house panels)
    are not per-ticker fetches and are excluded."""
    import ast as _ast

    names: list[str] = []
    for group in ("filters", "score", "context"):
        names += [c.get("fn") for c in spec.get(group) or []]
    for d in spec.get("derived") or []:
        try:
            names += [n.id for n in _ast.walk(_ast.parse(d["expr"], mode="eval"))
                      if isinstance(n, _ast.Name)]
        except SyntaxError:
            continue  # the validator rejects the spec before this matters
    kinds: set[str] = set()
    for name in names:
        entry = REGISTRY.get(name or "")
        if not entry:
            continue
        for prefix, kind in _KIND_OF_SOURCE_PREFIX:
            if entry["source"].startswith(prefix):
                kinds.add(kind)
                break
    return kinds


NEAR_MISS_CAP = 50


def _miss_distance(op: str, v: float, thr) -> float | None:
    """How far a failing value sits from its threshold, relative — the
    ordering that makes a near-miss list an entrance pipeline (closest
    first). None when closeness has no numeric meaning (set/percentile
    ops); those sort after every numeric miss."""
    try:
        if op in ("lt", "le"):
            return (v - float(thr)) / abs(float(thr)) if thr else abs(v - float(thr))
        if op in ("gt", "ge"):
            return (float(thr) - v) / abs(float(thr)) if thr else abs(v - float(thr))
        if op == "between":
            lo, hi = float(thr[0]), float(thr[1])
            span = (hi - lo) or abs(lo) or 1.0
            return (lo - v) / span if v < lo else (v - hi) / span
        if op == "eq":
            return abs(v - float(thr)) / abs(float(thr)) if thr else abs(v - float(thr))
    except (TypeError, ValueError, IndexError):
        return None
    return None


def _near_misses(spec: dict, cols: dict, masks: list, idx: pd.Index) -> tuple[list[dict], int]:
    """Names failing EXACTLY ONE filter, with the failing value shown
    (Kevin, 2026-11-09: near misses are the entrance pipeline). A failure
    on a missing (NaN) value is NOT a near miss — missing is not close;
    it belongs to the missing-data record. Returns (list, total): the
    list is closest-first and capped for the stored footer; the total
    always counts every near miss."""
    filters = spec.get("filters") or []
    if not filters or not masks:
        return [], 0
    fails = pd.DataFrame({j: ~m for j, m in enumerate(masks)})
    counts = fails.sum(axis=1)
    found = []
    for t in counts[counts == 1].index:
        j = int(fails.loc[t].to_numpy().argmax())
        f = filters[j]
        name = _col_name(f)
        raw = cols[name].loc[t]
        if raw is None or pd.isna(raw):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        found.append((_miss_distance(f["op"], v, f["value"]), t,
                      {"ticker": str(t), "fn": f["fn"], "column": name,
                       "value": v, "op": f["op"], "threshold": f["value"]}))
    found.sort(key=lambda x: (x[0] is None, x[0] if x[0] is not None else 0.0, x[1]))
    return [e for _, _, e in found[:NEAR_MISS_CAP]], len(found)


@dataclass
class RunResult:
    table: pd.DataFrame
    footer: dict
    spec: dict = dc_field(default_factory=dict)


def _is_union_rooted(universe: dict) -> bool:
    """True when the universe bottoms out in an index_union, through any
    wrapper chain (common_equity, sector). Round 2: a union universe is
    enriched in full -- the Round 1 timing evidence showed the wider run
    is the FAST path (the nightly warm-up covers exactly sp500+nasdaq100),
    and a cap on a union was the nondeterminism source: the recorded
    Buffett run enriched one 300-name subset and returned 40 survivors,
    a page-composed re-run enriched a different subset and returned 23."""
    node = universe or {}
    while node.get("type") in ("common_equity", "sector"):
        node = node.get("base") or {}
    return node.get("type") == "index_union"


def run_spec(spec: dict, store: DataStore | None = None) -> RunResult:
    validate_spec(spec)
    store = store or DataStore()
    tickers = resolve_universe(store, spec["universe"])
    universe_full = len(tickers)
    union_rooted = _is_union_rooted(spec["universe"])
    if union_rooted:
        cap = None
        selection = (f"all {universe_full} names enriched — union universe, "
                     "no enrichment cap")
    else:
        # A spec may carry its own cap (max_universe — the classic watchlist
        # screens' wider-universe option); specs without it get the standard
        # cap. A capped subset is the first `cap` names in SORTED ticker
        # order: the cohort must be a function of the ticker SET, never of
        # the order a refreshed universe file happens to list them in.
        cap = spec.get("max_universe") or MAX_UNIVERSE
        if universe_full > cap:
            tickers = sorted(tickers)[:cap]
            selection = (f"first {cap} of {universe_full} names in sorted "
                         "ticker order (enrichment cap)")
        else:
            selection = f"all {universe_full} names enriched"
    # Prefetch the per-ticker kinds this spec needs, concurrently, so the
    # field functions below read the local cache instead of fetching one
    # name at a time inside the request (Kevin, 2026-11-03).
    warm = getattr(store, "warm", None)
    if callable(warm):
        warm(tickers, needed_kinds(spec))
    idx = pd.Index(tickers, name="ticker")
    cols: dict[str, pd.Series] = {}
    used: list[str] = []

    def compute(call: dict) -> str:
        name = _col_name(call)
        if name not in cols:
            entry = REGISTRY[call["fn"]]
            s = entry["fn"](store, tickers, **(call.get("params") or {}))
            cols[name] = s.reindex(idx)
            used.append(name)
        return name

    # Derived ratios (Kevin, 2026-11-02): composed from base fields with the
    # validated arithmetic AST; a zero denominator yields NaN (missing --
    # the row fails filters on it), never an infinite "value".
    import ast as _ast

    def _eval(node, env: dict[str, pd.Series]) -> pd.Series:
        if isinstance(node, _ast.Expression):
            return _eval(node.body, env)
        if isinstance(node, _ast.Name):
            return env[node.id]
        if isinstance(node, _ast.Constant):
            return pd.Series(float(node.value), index=idx)
        if isinstance(node, _ast.UnaryOp):
            v = _eval(node.operand, env)
            return -v if isinstance(node.op, _ast.USub) else v
        left, right = _eval(node.left, env), _eval(node.right, env)
        with np.errstate(divide="ignore", invalid="ignore"):
            if isinstance(node.op, _ast.Add):
                return left + right
            if isinstance(node.op, _ast.Sub):
                return left - right
            if isinstance(node.op, _ast.Mult):
                return left * right
            return (left / right).replace([np.inf, -np.inf], np.nan)
        raise ValueError("unreachable: the spec validator gates the grammar")

    derived_src: dict[str, str] = {}
    for d in spec.get("derived") or []:
        refs = sorted({n.id for n in _ast.walk(_ast.parse(d["expr"], mode="eval"))
                       if isinstance(n, _ast.Name)})
        env = {ref: cols[compute({"fn": ref})] for ref in refs}
        cols[d["name"]] = _eval(_ast.parse(d["expr"], mode="eval"), env)
        used.append(d["name"])
        derived_src[d["name"]] = d["expr"]

    mask = pd.Series(True, index=idx)
    filter_report = []
    filter_masks: list[pd.Series] = []
    for f in spec.get("filters") or []:
        name = compute(f)
        m = _apply_op(cols[name], f["op"], f["value"])
        m = m.fillna(False)
        filter_report.append({"column": name, "op": f["op"], "value": f["value"],
                              "passed": int(m.sum())})
        filter_masks.append(m)
        mask &= m
    near_list, near_total = _near_misses(spec, cols, filter_masks, idx)

    score = None
    if spec.get("score"):
        total_w = sum(s["weight"] for s in spec["score"])
        score = pd.Series(0.0, index=idx)
        for s in spec["score"]:
            name = compute(s)
            pct = cols[name].rank(pct=True)
            if s.get("direction", "high") == "low":
                pct = 1.0 - pct
            score = score.add(pct.fillna(0.0) * (s["weight"] / total_w), fill_value=0.0)
        score = (score * 100.0).round(2)

    table = pd.DataFrame({name: cols[name] for name in used}, index=idx)
    if score is not None:
        table["score"] = score
    table = table[mask]
    sort = spec.get("sort") or ({"by": "score"} if score is not None else {})
    if sort.get("by"):
        by = sort["by"]
        if by in table.columns:
            table = table.sort_values(by, ascending=bool(sort.get("ascending", False)),
                                      na_position="last")
    # Round 3: the spec's `limit` is a DISPLAY limit ("show top N"), never
    # a cohort definition. The full filtered cohort is counted and listed
    # first; only the rows handed back for drawing are cut. Pre-fix, the
    # head() ran before the footer counted, so a builder limit of 25 made
    # a 40-name cohort report -- and, on the record path, RECORD -- itself
    # as 25.
    full_tickers = [str(t) for t in table.index] if len(table) else []
    if spec.get("limit"):
        table = table.head(int(spec["limit"]))
    displayed = int(len(table))
    table = table.reset_index()

    context = {}
    for c in spec.get("context") or []:
        entry = REGISTRY[c["fn"]]
        key = _col_name(c)
        try:
            context[key] = entry["fn"](store, None, **(c.get("params") or {}))
        except Exception as e:  # context is informational: record, never abort
            context[key] = {"value": None, "error": str(e)[:200]}
            store.note_missing("*", c["fn"], f"context fetch failed: {e}")

    columns_prov = {}
    for name in used:
        if name in derived_src:
            columns_prov[name] = {"fn": "derived", "source": f"derived: {derived_src[name]}",
                                  "as_of": None}
            continue
        fn_name = name.split("(")[0]
        entry = REGISTRY[fn_name]
        kind = next((v for k, v in _SOURCE_KIND.items() if entry["source"].startswith(k)),
                    None)
        columns_prov[name] = {"fn": fn_name, "source": entry["source"],
                              "as_of": store.asof.get(kind) if kind else None}
    used_fns = {name.split("(")[0] for name in used}
    used_fns |= {c["fn"] for c in spec.get("context") or []}
    ages = [p["as_of"] for p in columns_prov.values() if p.get("as_of")]
    footer = {
        "spec_name": spec["name"],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_as_of": min(ages) if ages else None,
        "universe_size": len(tickers),
        **({"universe_capped": {"cap": cap, "universe_size_full": universe_full}}
           if cap is not None and universe_full > cap else {}),
        "universe_selection": selection,
        **({"universe_union": True} if union_rooted else {}),
        # TRUE filter counts, computed on the full cohort before any
        # display cut (Round 3). `displayed` says how many rows the
        # payload carries; when it is smaller, `display_limit` names the
        # limit that cut the display -- the header renders "showing
        # displayed of survivors", never the cut as the count.
        "survivors": len(full_tickers),
        "survivor_tickers": full_tickers,
        "displayed": displayed,
        **({"display_limit": int(spec["limit"])}
           if spec.get("limit") and displayed < len(full_tickers) else {}),
        # Rows and issuers both: dual-class names (GOOG + GOOGL) are two
        # rows of one issuer. Sidecar names only -- no fetch for a count.
        **({"survivor_issuers": len({issuer_key(t) for t in full_tickers})}
           if full_tickers else {}),
        **({"near_misses": near_list, "near_miss_count": near_total} if near_total else {}),
        "filters": filter_report,
        "columns": columns_prov,
        "context": context,
        "missing": [m for m in store.missing if m["field"] in used_fns],
        "spec_echo": spec,
    }
    return RunResult(table=table, footer=footer, spec=spec)
