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
from .universes import resolve_universe

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


@dataclass
class RunResult:
    table: pd.DataFrame
    footer: dict
    spec: dict = dc_field(default_factory=dict)


def run_spec(spec: dict, store: DataStore | None = None) -> RunResult:
    validate_spec(spec)
    store = store or DataStore()
    tickers = resolve_universe(store, spec["universe"])
    universe_full = len(tickers)
    if universe_full > MAX_UNIVERSE:
        tickers = tickers[:MAX_UNIVERSE]
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
    for f in spec.get("filters") or []:
        name = compute(f)
        m = _apply_op(cols[name], f["op"], f["value"])
        m = m.fillna(False)
        filter_report.append({"column": name, "op": f["op"], "value": f["value"],
                              "passed": int(m.sum())})
        mask &= m

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
    if spec.get("limit"):
        table = table.head(int(spec["limit"]))
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
    footer = {
        "spec_name": spec["name"],
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_size": len(tickers),
        **({"universe_capped": {"cap": MAX_UNIVERSE, "universe_size_full": universe_full}}
           if universe_full > MAX_UNIVERSE else {}),
        "survivors": int(len(table)),
        "filters": filter_report,
        "columns": columns_prov,
        "context": context,
        "missing": [m for m in store.missing if m["field"] in used_fns],
        "spec_echo": spec,
    }
    return RunResult(table=table, footer=footer, spec=spec)
