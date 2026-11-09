"""The portfolio check (Kevin, 2026-11-09): a portfolio-level gate on ideas and orders.

Order-level fences (caps per key, the defined-risk guard, the breakers) judge an order
alone. This module judges it against the BOOK it lands on: the post-trade thesis
weights against the Multi-Thesis caps, the factor clusters the cohesion analysis
(~/workspace/ibkr-comp/research/portfolio_cohesion_2026-11-09.md) showed hiding inside
the sleeves, and the order sleeve's correlation to the book it joins. One engine, three
callers, so they can never disagree: the machine preflight/placement path
(machine_api.validate_order), idea activations (go-live / auto-on), and the Portfolio
page's card (GET /api/portfolio/portfolio-check) all read from here.

The rules, as configured (the config is the law -- see load_config):
- BLOCKING, on post-trade weights as % of invested: T4 ballast members inside their
  2-8% band; the T8 sleeve at most 10%; T2 names at most 5% each; the index sleeve at
  most 25%; any other single name at most 5%; GLD at most 12% (its own override: a
  ~11% target while the trim works it down from 21.6%). A block fires only when the
  order itself moves the capped entity deeper into breach -- an exit that reduces an
  over-cap position always passes, because the exit is the cure, never a new breach.
- IBIT is EXIT-ONLY: any order that increases IBIT exposure blocks; closes pass.
- Kevin's ruling (2026-11-09, "exits always win over the floor"): when the machine
  door's exit classification (the #440 book math -- never a caller flag, threaded in
  as `is_exit`) says the order is an exit, a member-FLOOR breach it causes is a
  WARNING, not a block. The floor still blocks every non-exit reduction, and caps
  are untouched by the ruling. Activations pass no exit flag: their floor behavior
  is exactly as originally shipped.
- WARNINGS (never blocking): a cluster (rates trio, AI complex, gold) whose share of
  invested rises more than 2 points on one order; gold over 12% of invested.
- Correlation is informational: the order sleeve's stored daily-return series
  against the book's (portfolio_series, refreshed weekly by
  tradehub.scripts.portfolio_series_refresh), Pearson over the shared days.

Weights are % of INVESTED (the signed sum of position market values -- equity minus
cash), the cohesion report's basis. Caps bite only once the post-trade book holds at
least `min_invested_for_caps` dollars invested: below that the book is a stub or a
seed being built, and a percentage of almost-nothing is not a cohesion fact.
"""

from __future__ import annotations

import copy
import math
from datetime import datetime, timezone
from typing import Any

TARGETS_TABLE = "portfolio_targets"
EVENTS_TABLE = "portfolio_check_events"
SERIES_TABLE = "portfolio_series"

# The seed (migration 20261109000004): sleeve membership and caps from the cohesion
# analysis's own constrained-optimizer bounds, with GLD's per-name override.
DEFAULT_CONFIG: dict[str, Any] = {
    "sleeves": {
        "t4_ballast": {"label": "T4 ballast (W18 core)",
                       "symbols": ["GLD", "XLP", "XLU", "XLRE", "XLV", "VNQ", "DBC", "USO"],
                       "member_min_pct": 2.0, "member_max_pct": 8.0},
        "t2_kshape": {"label": "T2 K-shape carry",
                      "symbols": ["DLTR", "DG", "MO", "WSM"],
                      "member_max_pct": 5.0},
        "t3_index": {"label": "T3 index",
                     "symbols": ["SPY", "VOO"],
                     "sleeve_max_pct": 25.0},
        "t8_ai": {"label": "T8 AI winners core",
                  "symbols": ["AAPL", "NVDA", "MSFT", "AVGO", "MU", "TSM"],
                  "sleeve_max_pct": 10.0, "equal_inside": True},
        "ibit": {"label": "IBIT BTC sleeve",
                 "symbols": ["IBIT"],
                 "exit_only": True},
        "t7_legacy": {"label": "T7 legacy chips",
                      "symbols": ["TXN", "INTC"]},
    },
    # Per-name overrides win over sleeve member bands and the single-name rule.
    "name_overrides": {
        "GLD": {"target_pct": 11.0, "max_pct": 12.0},
    },
    "single_name_max_pct": 5.0,
    "clusters": {
        "rates": {"label": "Rates factor", "symbols": ["XLU", "XLRE", "VNQ"],
                  "flag_symbols": ["GLD"]},
        "ai_complex": {"label": "AI complex",
                       "symbols": ["AAPL", "NVDA", "MSFT", "AVGO", "MU", "TSM", "TXN", "INTC"]},
        "gold": {"label": "Gold", "symbols": ["GLD"], "max_pct": 12.0},
    },
    "warn_cluster_rise_pts": 2.0,
    # Order tag -> sleeve, for attribution. Sleeve membership by symbol governs the
    # weights themselves; the tag names the thesis an order belongs to when it says so.
    "tag_map": {"ai-tech-core": "t8_ai"},
    "min_invested_for_caps": 10_000.0,
}


# ── config ─────────────────────────────────────────────────────────────────────

def _merge(base: dict, over: dict) -> dict:
    """Deep-merge the stored config over the seed: a partial edit (one cap) can
    never silently drop a sleeve or a cluster it didn't mention."""
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def load_config(supa) -> dict:
    """The targets state: the portfolio_targets 'global' row when present, else the
    seed -- merged over the seed either way. Read at evaluation time, so editing the
    row changes verdicts with no code change and no deploy."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    if supa is None:
        return config
    try:
        rows = supa.table(TARGETS_TABLE).select("config").eq("scope", "global").execute().data
    except Exception:  # noqa: BLE001 -- a missing table (pre-migration) reads as the seed
        return config
    if rows and isinstance(rows[0].get("config"), dict):
        _merge(config, rows[0]["config"])
    return config


def sleeve_of(symbol: str, config: dict) -> str | None:
    for sleeve_id, sleeve in config["sleeves"].items():
        if symbol in sleeve.get("symbols", []):
            return sleeve_id
    return None


def attribute(tag: str | None, symbol: str, config: dict) -> dict:
    """The thesis an order belongs to: its tag when the tag names one, else its
    symbol's sleeve, else unassigned (an event name, most often)."""
    if tag and tag in config.get("tag_map", {}):
        sleeve_id = config["tag_map"][tag]
        return {"id": sleeve_id, "label": config["sleeves"][sleeve_id]["label"], "via": "tag"}
    sleeve_id = sleeve_of(symbol, config)
    if sleeve_id is not None:
        return {"id": sleeve_id, "label": config["sleeves"][sleeve_id]["label"], "via": "symbol"}
    return {"id": None, "label": "Unassigned", "via": "unassigned"}


# ── book reads ─────────────────────────────────────────────────────────────────

def positions_by_underlying(book: str | None) -> dict[str, dict]:
    """Underlying -> {qty, mv} for the book's positions, OCC rows bucketed to their
    underlying (a short SPY call is SPY exposure). MV falls back market_value ->
    qty x current_price -> the door's own pricing (fetch_mid for contracts,
    latest_price for shares); a row with no readable price counts 0 and is named in
    `unpriced`. Read failures propagate -- callers decide what an unreadable book
    means for their door."""
    from tradehub.portfolio import option_orders
    from tradehub.portfolio.alpaca_paper import latest_price, paper_get
    from tradehub.portfolio.options import fetch_mid, parse_occ

    out: dict[str, dict] = {}
    unpriced: list[str] = []
    for row in paper_get("/v2/positions", book=book) or []:
        symbol = option_orders.clean_symbol(row.get("symbol"))
        if not symbol:
            continue
        try:
            qty = float(row.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        mv = row.get("market_value")
        if mv is None and row.get("current_price") is not None:
            try:
                mv = qty * float(row["current_price"])
            except (TypeError, ValueError):
                mv = None
        if mv is None:
            try:
                px = fetch_mid(symbol, book=book) if option_orders.is_option_symbol(symbol) \
                    else latest_price(symbol, book=book)
                mv = qty * float(px) * (100 if option_orders.is_option_symbol(symbol) else 1) \
                    if px is not None else None
            except Exception:  # noqa: BLE001 -- one unpriceable row must not sink the read
                mv = None
        if mv is None:
            mv = 0.0
            unpriced.append(symbol)
        else:
            mv = float(mv)
        underlying = symbol
        if option_orders.is_option_symbol(symbol):
            try:
                underlying = parse_occ(symbol)["underlying"]
            except ValueError:
                underlying = symbol
        slot = out.setdefault(underlying, {"qty": 0.0, "mv": 0.0})
        slot["qty"] += qty
        slot["mv"] += mv
    if unpriced:
        out["__unpriced__"] = {"qty": 0.0, "mv": 0.0, "symbols": unpriced}
    return out


def load_series(supa, book: str) -> tuple[dict[str, list], str | None]:
    """Stored return series for one book: {series_key: [[day, ret], ...]} and the
    refresh stamp. Missing table/rows read as empty -- the readout degrades to a
    note, never an error."""
    if supa is None:
        return {}, None
    try:
        rows = supa.table(SERIES_TABLE).select("*").eq("book", book).execute().data or []
    except Exception:  # noqa: BLE001
        return {}, None
    series = {r["series_key"]: r.get("days") or [] for r in rows}
    refreshed = max((r.get("refreshed_at") or "" for r in rows), default="") or None
    return series, refreshed


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 60:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def correlation(order_key: str | None, series: dict[str, list]) -> dict:
    """The order sleeve's correlation to the book series, from stored series only."""
    if order_key is None:
        return {"series": None, "corr": None, "days": 0,
                "note": "the order has no sleeve series to correlate"}
    mine = {d: r for d, r in series.get(order_key, [])}
    book = {d: r for d, r in series.get("__book__", [])}
    shared = sorted(set(mine) & set(book))
    corr = _pearson([mine[d] for d in shared], [book[d] for d in shared]) if shared else None
    if corr is None:
        return {"series": order_key, "corr": None, "days": len(shared),
                "note": "not enough stored history yet (the weekly series refresh builds it)"}
    return {"series": order_key, "corr": round(corr, 2), "days": len(shared), "note": None}


# ── the evaluation (pure) ──────────────────────────────────────────────────────

def _weights(mv_by_name: dict[str, float], config: dict) -> dict:
    invested = sum(mv_by_name.values())
    names = {s: (mv / invested * 100 if invested > 0 else 0.0) for s, mv in mv_by_name.items()}
    sleeves = {}
    for sleeve_id, sleeve in config["sleeves"].items():
        sleeves[sleeve_id] = sum(names.get(s, 0.0) for s in sleeve.get("symbols", []))
    return {"invested": invested, "names": names, "sleeves": sleeves}


def _clusters(mv_by_name: dict[str, float], invested: float, config: dict) -> dict:
    out = {}
    for cluster_id, cluster in config["clusters"].items():
        mv = sum(mv_by_name.get(s, 0.0) for s in cluster.get("symbols", []))
        entry = {"label": cluster["label"],
                 "pct": mv / invested * 100 if invested > 0 else 0.0,
                 "mv": mv}
        if cluster.get("flag_symbols"):
            entry["with_flagged_pct"] = (
                (mv + sum(mv_by_name.get(s, 0.0) for s in cluster["flag_symbols"]))
                / invested * 100 if invested > 0 else 0.0)
        out[cluster_id] = entry
    return out


def evaluate(positions: dict[str, dict], deltas: dict[str, float], config: dict, *,
             tag: str | None = None, series: dict | None = None,
             is_exit: bool = False) -> dict:
    """Judge one order (or one activation envelope) against the book.

    `positions`: underlying -> {"qty", "mv"} as positions_by_underlying returns.
    `deltas`: underlying -> signed market-value change the order makes (a buy is
    positive, whatever wrapper it arrives in -- shares, a leg, a whole package).
    `is_exit`: the machine door's exit classification (book math, #440) for THIS
    order; it downgrades a member-floor breach to a named warning and nothing
    else (Kevin's ruling, 2026-11-09). Activation envelopes never pass it.
    Pure: no reads, no writes, so every caller and every test sees the same math."""
    mv_pre = {s: float(p.get("mv") or 0.0) for s, p in positions.items()
              if not s.startswith("__")}
    mv_post = dict(mv_pre)
    for symbol, delta in deltas.items():
        mv_post[symbol] = mv_post.get(symbol, 0.0) + float(delta)
    pre = _weights(mv_pre, config)
    post = _weights(mv_post, config)
    order_symbol = next(iter(deltas), "")
    thesis = attribute(tag, order_symbol, config)
    corr_key = thesis["id"] or (f"sym:{order_symbol}" if order_symbol else None)

    base = {"thesis": thesis,
            "weights": {"invested": round(post["invested"], 2),
                        "names": {s: round(w, 2) for s, w in post["names"].items()},
                        "sleeves": {s: round(w, 2) for s, w in post["sleeves"].items()}},
            "clusters": {}, "correlation": correlation(corr_key, series or {}),
            "blocks": [], "warnings": []}
    invested = post["invested"]
    if invested < float(config.get("min_invested_for_caps", 0.0)):
        base["clusters"] = {k: {"label": v["label"], "pct": round(v["pct"], 2),
                                **({"with_flagged_pct": round(v["with_flagged_pct"], 2)}
                                   if "with_flagged_pct" in v else {})}
                            for k, v in _clusters(mv_post, invested, config).items()}
        base["outcome"] = "pass"
        base["detail"] = (f"the book holds ${invested:,.0f} invested; the cohesion caps "
                          "bite once it holds "
                          f"${float(config.get('min_invested_for_caps', 0.0)):,.0f}")
        return base

    blocks: list[dict] = []
    warnings: list[dict] = []

    def deeper(name: str) -> bool:
        """The order adds dollars to this entity -- the only way it can deepen a breach."""
        return mv_post.get(name, 0.0) > mv_pre.get(name, 0.0)

    def sleeve_deeper(sleeve_id: str) -> bool:
        symbols = config["sleeves"][sleeve_id].get("symbols", [])
        return sum(mv_post.get(s, 0.0) for s in symbols) > sum(mv_pre.get(s, 0.0) for s in symbols)

    # IBIT exit-only: any increase in IBIT exposure, in any wrapper, blocks.
    for sleeve_id, sleeve in config["sleeves"].items():
        if not sleeve.get("exit_only"):
            continue
        for symbol in sleeve.get("symbols", []):
            if float(deltas.get(symbol, 0.0)) > 0:
                blocks.append({"rule": "exit_only",
                               "detail": f"{symbol} is exit-only: this order increases "
                                         f"{symbol} exposure, and only closes pass"})

    # Per-name caps: an explicit override wins; else the sleeve member band; else
    # the single-name rule for anything outside the index sleeve.
    index_symbols = set(config["sleeves"].get("t3_index", {}).get("symbols", []))
    for symbol in sorted(set(mv_post) | set(deltas)):
        post_w = post["names"].get(symbol, 0.0)
        override = config.get("name_overrides", {}).get(symbol)
        sleeve_id = sleeve_of(symbol, config)
        sleeve = config["sleeves"].get(sleeve_id, {}) if sleeve_id else {}
        if override and override.get("max_pct") is not None:
            cap, cap_label = float(override["max_pct"]), f"{symbol}'s cap of {override['max_pct']:g}%"
        elif sleeve.get("member_max_pct") is not None:
            cap = float(sleeve["member_max_pct"])
            cap_label = f"the {sleeve['label']} member cap of {cap:g}%"
        elif symbol not in index_symbols and config.get("single_name_max_pct") is not None:
            cap = float(config["single_name_max_pct"])
            cap_label = f"the single-name cap of {cap:g}%"
        else:
            cap, cap_label = None, ""
        if cap is not None and post_w > cap and deeper(symbol):
            blocks.append({"rule": "name_cap",
                           "detail": f"{symbol} would be {post_w:.1f}% of invested after "
                                     f"this order, over {cap_label}"})
        floor = override.get("min_pct") if override and override.get("min_pct") is not None \
            else sleeve.get("member_min_pct")
        if floor is not None and post_w < float(floor) and not deeper(symbol) \
                and mv_post.get(symbol, 0.0) < mv_pre.get(symbol, 0.0):
            if is_exit:
                # Kevin's ruling (2026-11-09): exits win over the floor. The
                # breach is still named -- in the block and, via the recorded
                # event, in the card's recent outcomes -- but it cannot refuse
                # an order the book math classifies as an exit.
                warnings.append({"rule": "member_floor_exit",
                                 "detail": f"{symbol} would be {post_w:.1f}% of invested "
                                           f"after this order, under the "
                                           f"{sleeve.get('label', symbol)} floor of "
                                           f"{float(floor):g}% -- an exit crossing a "
                                           "member floor, allowed per Kevin's ruling: "
                                           "exits win over the floor"})
            else:
                blocks.append({"rule": "member_floor",
                               "detail": f"{symbol} would be {post_w:.1f}% of invested after "
                                         f"this order, under the {sleeve.get('label', symbol)} "
                                         f"floor of {float(floor):g}%"})

    # Sleeve caps.
    for sleeve_id, sleeve in config["sleeves"].items():
        cap = sleeve.get("sleeve_max_pct")
        if cap is None:
            continue
        post_w = post["sleeves"].get(sleeve_id, 0.0)
        if post_w > float(cap) and sleeve_deeper(sleeve_id):
            blocks.append({"rule": "sleeve_cap",
                           "detail": f"the {sleeve['label']} sleeve would be {post_w:.1f}% "
                                     f"of invested after this order, over its cap of "
                                     f"{float(cap):g}%"})

    # Factor stacking: warnings only.
    pre_clusters = _clusters(mv_pre, pre["invested"], config)
    post_clusters = _clusters(mv_post, invested, config)
    rise_bar = float(config.get("warn_cluster_rise_pts", 2.0))
    for cluster_id, cluster in config["clusters"].items():
        rise = post_clusters[cluster_id]["pct"] - pre_clusters[cluster_id]["pct"]
        if rise > rise_bar:
            warnings.append({"rule": "cluster_rise",
                             "detail": f"the {cluster['label']} cluster rises {rise:.1f} "
                                       f"points to {post_clusters[cluster_id]['pct']:.1f}% "
                                       "of invested on this order"})
        cap = cluster.get("max_pct")
        if cap is not None and post_clusters[cluster_id]["pct"] > float(cap):
            warnings.append({"rule": "cluster_over",
                             "detail": f"{cluster['label'].lower()} is "
                                       f"{post_clusters[cluster_id]['pct']:.1f}% of invested "
                                       f"after this order, over its {float(cap):g}% flag"})

    base["clusters"] = {k: {"label": v["label"], "pct": round(v["pct"], 2),
                            **({"with_flagged_pct": round(v["with_flagged_pct"], 2)}
                               if "with_flagged_pct" in v else {})}
                        for k, v in post_clusters.items()}
    base["blocks"] = blocks
    base["warnings"] = warnings
    base["outcome"] = "block" if blocks else "warn" if warnings else "pass"
    if blocks:
        base["detail"] = blocks[0]["detail"]
    elif warnings:
        base["detail"] = warnings[0]["detail"]
    else:
        base["detail"] = (f"portfolio check passes: {thesis['label']} order leaves every "
                          "thesis weight inside its cap")
    return base


# ── orchestration: reads, evaluation, the recorded outcome ─────────────────────

def record_event(supa, book: str, source: str, symbol: str | None, block: dict) -> None:
    """One row in portfolio_check_events -- the card's recent-outcomes feed and the
    check's audit trail. Best-effort by design: recording must never break the
    order it describes (the journal-store lesson), so failures are swallowed."""
    if supa is None:
        return
    try:
        supa.table(EVENTS_TABLE).insert(
            {"book": book, "source": source, "symbol": symbol,
             "outcome": block.get("outcome"), "detail": block.get("detail"),
             "block": block}).execute()
    except Exception:  # noqa: BLE001
        pass


def check_order(supa, book: str, deltas: dict[str, float], *, source: str,
                symbol: str | None = None, tag: str | None = None,
                idea_id: int | None = None, record: bool = True,
                is_exit: bool = False) -> dict:
    """The gate, end to end: read the book, evaluate, record. An unreadable book
    (AccountNotConnected, a failed read) yields outcome "unavailable" and NO
    block: placement itself is impossible without the account, and the entry is
    stated in the block rather than hidden -- the check never silently passes."""
    config = load_config(supa)
    if tag is None and idea_id is not None and supa is not None:
        # The idea->thesis mapping: an idea's own tags (Kevin's groupings on the
        # idea row) name its thesis when one of them is a known tag_map slug.
        try:
            rows = supa.table("ideas").select("tags").eq("id", idea_id).execute().data
            for candidate in (rows[0].get("tags") or []) if rows else []:
                if candidate in config.get("tag_map", {}):
                    tag = candidate
                    break
        except Exception:  # noqa: BLE001 -- attribution is enrichment here
            pass
    try:
        positions = positions_by_underlying(book)
        series, _ = load_series(supa, book)
    except Exception as exc:  # noqa: BLE001 -- stated, not hidden; see the docstring
        block = {"outcome": "unavailable", "thesis": attribute(tag, symbol or "", config),
                 "blocks": [], "warnings": [],
                 "detail": f"portfolio check unavailable: the book could not be read "
                           f"({type(exc).__name__})",
                 "weights": None, "clusters": {}, "correlation": None}
        if record:
            record_event(supa, book, source, symbol, block)
        return block
    block = evaluate(positions, deltas, config, tag=tag, series=series,
                     is_exit=is_exit)
    if record:
        record_event(supa, book, source, symbol, block)
    return block


# ── the card: current state against the same config ────────────────────────────

def _status(weight: float, *, target: float | None = None, max_pct: float | None = None,
            min_pct: float | None = None) -> str:
    if max_pct is not None and weight > max_pct:
        return "over"
    if min_pct is not None and weight < min_pct:
        return "under"
    return "ok"


def current_state(supa, book: str) -> dict:
    """The Portfolio card's payload: thesis weights vs caps/targets with status,
    the three cluster exposures, cash %, sleeve correlations to the book, and the
    most recent check outcomes -- all from the same engine and stored state the
    gate reads, so the card and the gate can never disagree."""
    from tradehub.portfolio.alpaca_paper import paper_get

    config = load_config(supa)
    positions = positions_by_underlying(book)
    account = paper_get("/v2/account", book=book) or {}
    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    mv = {s: float(p.get("mv") or 0.0) for s, p in positions.items() if not s.startswith("__")}
    w = _weights(mv, config)
    series, refreshed_at = load_series(supa, book)

    sleeves = []
    for sleeve_id, sleeve in config["sleeves"].items():
        members = []
        for symbol in sleeve.get("symbols", []):
            override = config.get("name_overrides", {}).get(symbol, {})
            max_pct = override.get("max_pct", sleeve.get("member_max_pct"))
            min_pct = override.get("min_pct", sleeve.get("member_min_pct"))
            target = override.get("target_pct")
            if target is None and sleeve.get("equal_inside") and sleeve.get("sleeve_max_pct"):
                target = float(sleeve["sleeve_max_pct"]) / len(sleeve["symbols"])
            weight = w["names"].get(symbol, 0.0)
            members.append({"symbol": symbol, "weight_pct": round(weight, 2),
                            "target_pct": target,
                            "max_pct": max_pct, "min_pct": min_pct,
                            "status": _status(weight, max_pct=max_pct, min_pct=min_pct)})
        weight = w["sleeves"].get(sleeve_id, 0.0)
        sleeves.append({"id": sleeve_id, "label": sleeve["label"],
                        "weight_pct": round(weight, 2),
                        "sleeve_max_pct": sleeve.get("sleeve_max_pct"),
                        "exit_only": bool(sleeve.get("exit_only")),
                        "status": _status(weight, max_pct=sleeve.get("sleeve_max_pct")),
                        "members": members,
                        "correlation_to_book": correlation(sleeve_id, series)["corr"]})
    unassigned = [{"symbol": s, "weight_pct": round(wt, 2)}
                  for s, wt in sorted(w["names"].items())
                  if sleeve_of(s, config) is None and abs(wt) > 0.005]
    clusters = {k: {"label": v["label"], "pct": round(v["pct"], 2),
                    **({"with_flagged_pct": round(v["with_flagged_pct"], 2)}
                       if "with_flagged_pct" in v else {})}
                for k, v in _clusters(mv, w["invested"], config).items()}
    events: list[dict] = []
    if supa is not None:
        try:
            rows = supa.table(EVENTS_TABLE).select("*").eq("book", book) \
                .order("at", desc=True).execute().data or []
            events = [{"at": r.get("at"), "source": r.get("source"),
                       "symbol": r.get("symbol"), "outcome": r.get("outcome"),
                       "detail": r.get("detail")} for r in rows[:8]]
        except Exception:  # noqa: BLE001 -- the card still renders without its feed
            events = []
    targets_updated = None
    if supa is not None:
        try:
            rows = supa.table(TARGETS_TABLE).select("updated_at").eq("scope", "global").execute().data
            targets_updated = rows[0].get("updated_at") if rows else None
        except Exception:  # noqa: BLE001
            targets_updated = None
    return {"book": book, "as_of": datetime.now(timezone.utc).isoformat(),
            "equity": equity, "cash": cash,
            "cash_pct": round(cash / equity * 100, 2) if equity > 0 else None,
            "invested": round(w["invested"], 2),
            "sleeves": sleeves, "unassigned": unassigned, "clusters": clusters,
            "recent_checks": events,
            "targets_updated_at": targets_updated,
            "series_refreshed_at": refreshed_at,
            "unpriced": positions.get("__unpriced__", {}).get("symbols", [])}
