"""Spec C — the band-crossing engine, LOG-ONLY build (Kevin, 2026-11-09).

Rules v1 are frozen in docs/superpowers/specs/2026-11-09-band-crossing-
engine-freeze.md, which governs this module: deterministic Guidance bands
plus guide status make a repeatable single-name signal — a would-be long
starter at/below the base band with the guide intact or raised (2% of
book, 4% at/below bear), a trim above the bull band, a full-exit REVIEW
flag when the file has deteriorated, and defined-risk put spreads as the
only short — graded against same-name buy-and-hold by the frozen
falsifier computation.

LOG-ONLY is structural here, not a mode flag on an order path: this
module contains no order-placement code of any kind. It computes
crossings, runs the Portfolio Check on each would-be activation
(recording off — the outcome lands on the crossing row, never in
manual_actions), and writes the crossing log. The
`band_crossing_controls` row (gap_controls precedent, PR #451) is read
every scan and stamped on every row as the mode; it is the FUTURE live
build's switch — flipping it against this build activates nothing,
because there is nothing here to switch on.

T1 forward-file classifications have no machine-readable store in the
hub today (checked 2026-11-09: no such table exists; the forward file
lives as research documents). `t1_classification` reads the one provider
contract — a `forward_file_classifications` table — and honestly
returns None until a source exists, so the T1-dependent rules (shorts,
the review escalation) cannot fire and the reason is recorded wherever
they would have been evaluated. Classifications are never invented or
inferred from guide direction.

Spec D's level watcher (Stage 1) drives this same state machine at
intraday prices through run_watcher_evaluation — the Spec C amendment
to Spec D: one band-crossing detector, ever. The watcher adds the
real-time trigger/alert layer; it does not fork the transition logic.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone

CONTROLS = "band_crossing_controls"
SCANS = "band_crossing_scans"
STATE = "band_crossing_state"
CROSSINGS = "band_crossings"
T1_TABLE = "forward_file_classifications"

BOOKS = ("main", "big")
ENTRY_ACTIONS = ("starter", "add", "short_put_spread")
SHORT_UNIT_USD = 1_500.0          # the standard defined-risk unit (spec)
STARTER_PCT = 2.0                 # % of book at/below base
ADD_PCT = 4.0                     # % of book at/below bear
FALSIFIER_GATE = 20               # graded entries before the verdict
_GATE_REASONS = ("guide_cut", "guide_status_unknown", "no_t1_classification")
_MISSING_TABLE = ("does not exist", "42P01", "PGRST205", "schema cache")


# ── pure logic: zones, guide status, the candidate ───────────────────────────

def zone_of(price: float, bands: dict) -> str:
    """Where the price sits vs the bands (frozen zone table)."""
    if price <= float(bands["bear"]):
        return "bear"
    if price <= float(bands["base"]):
        return "base"
    if price <= float(bands["bull"]):
        return "bull"
    return "above_bull"


def guide_status_of(sheet: dict) -> tuple[str, str | None]:
    """(status, raw direction) for the sheet's anchor metric: raised ->
    raised; held/first -> intact (a first guide is the guide — nothing was
    cut); cut -> cut; no recorded direction -> unknown."""
    metric = (sheet.get("anchor") or {}).get("metric")
    raw = ((sheet.get("directions") or {}).get(metric) or {}).get("direction")
    if raw == "raised":
        return "raised", raw
    if raw in ("held", "first"):
        return "intact", raw
    if raw == "cut":
        return "cut", raw
    return "unknown", raw


def industry_of(sheet: dict) -> str:
    group = sheet.get("peer_group") or ""
    if group.startswith("sector:"):
        group = group[len("sector:"):]
    return group or "unknown"


def candidate(*, zone: str, guide_status: str, t1: str | None,
              held_mv: float, equity: float) -> dict:
    """The would-be action for one (name, book) at one scan — rules v1,
    pure. Returns {action, target_pct, delta_usd, suppress_reason}; action
    None with a suppress_reason names the gate that stopped it, action
    None with no reason means no rule applies."""
    none = {"action": None, "target_pct": None, "delta_usd": None,
            "suppress_reason": None}
    if zone in ("bear", "base"):
        if guide_status == "cut":
            return {**none, "suppress_reason": "guide_cut"}
        if guide_status not in ("intact", "raised"):
            return {**none, "suppress_reason": "guide_status_unknown"}
        target_pct = ADD_PCT if zone == "bear" else STARTER_PCT
        target_usd = equity * target_pct / 100.0
        held = max(float(held_mv or 0.0), 0.0)
        if held >= target_usd - 0.01:
            return {**none, "suppress_reason": "target_reached"}
        return {"action": "starter" if held <= 0 else "add",
                "target_pct": target_pct,
                "delta_usd": target_usd - held,
                "suppress_reason": None}
    if zone == "above_bull":
        held = float(held_mv or 0.0)
        if held > 0:
            if t1 == "deteriorated":
                return {"action": "review_full_exit", "target_pct": None,
                        "delta_usd": None, "suppress_reason": None}
            return {"action": "trim_half", "target_pct": None,
                    "delta_usd": -0.5 * held, "suppress_reason": None}
        if t1 == "deteriorated":
            return {"action": "short_put_spread", "target_pct": None,
                    "delta_usd": -SHORT_UNIT_USD, "suppress_reason": None}
        if t1 is None:
            return {**none, "suppress_reason": "no_t1_classification"}
        return none
    return none


# ── the control row ──────────────────────────────────────────────────────────

def orders_enabled(client) -> bool:
    """The future live build's switch: the band_crossing_controls 'global'
    row. This build is born log-only, so EVERY failure mode reads OFF —
    a missing table (pre-migration) and any read error included: unlike
    the gap desks' switch, there is no older behavior to preserve, and a
    transient error must never read as permission."""
    try:
        rows = (client.table(CONTROLS).select("orders_enabled")
                .eq("scope", "global").execute().data) or []
    except Exception:  # noqa: BLE001 -- born log-only: off is the only default
        return False
    return bool(rows[0]["orders_enabled"]) if rows else False


# ── T1 classifications: the provider contract ────────────────────────────────

def t1_classification(client, ticker: str) -> str | None:
    """The name's T1 forward-file classification ('improved' / 'intact' /
    'deteriorated'), latest row wins — or None when no source exists.
    Today the table does not exist in the hub, so this returns None for
    every name; that absence gates the short and review rules, it is not
    papered over."""
    if client is None:
        return None
    try:
        rows = (client.table(T1_TABLE).select("classification, as_of")
                .eq("ticker", ticker).order("as_of", desc=True)
                .limit(1).execute().data) or []
    except Exception:  # noqa: BLE001 -- no source yet is an honest None
        return None
    if not rows:
        return None
    value = rows[0].get("classification")
    return value if value in ("improved", "intact", "deteriorated") else None


# ── store helpers ────────────────────────────────────────────────────────────

def _state_row(client, ticker: str, book: str) -> dict | None:
    rows = (client.table(STATE).select("*").eq("ticker", ticker)
            .eq("book", book).execute().data) or []
    return rows[0] if rows else None


def _save_state(client, ticker: str, book: str, state: dict) -> None:
    if _state_row(client, ticker, book) is None:
        client.table(STATE).insert({"ticker": ticker, "book": book,
                                    **state}).execute()
    else:
        client.table(STATE).update(state).eq("ticker", ticker) \
            .eq("book", book).execute()


def _default_positions(book: str) -> dict:
    from tradehub.portfolio import portfolio_check

    return portfolio_check.positions_by_underlying(book)


def _default_equity(book: str) -> float:
    from tradehub.portfolio.alpaca_paper import paper_get

    account = paper_get("/v2/account", book=book) or {}
    return float(account.get("equity") or 0.0)


def _default_pc(client, book: str, ticker: str, delta: float):
    """The Portfolio Check on a would-be activation, recording OFF: the
    outcome lands on the crossing row only — never in
    portfolio_check_events, never in manual_actions (log-only)."""
    from tradehub.portfolio import portfolio_check

    block = portfolio_check.check_order(
        client, book, {ticker: float(delta)}, source="band_crossing_log_only",
        symbol=ticker, record=False)
    outcome = {"block": "would_block", "warn": "would_warn",
               "pass": "would_pass"}.get(block.get("outcome"), "unavailable")
    return outcome, block.get("detail")


# ── the transition step (shared by the scans and Spec D's watcher) ──────────

_OMIT = object()  # sentinel: leave the key out of the insert entirely


def _evaluate_book(client, *, sheet: dict, ticker: str, book: str,
                   price: float, price_as_of, zone: str,
                   guide_status: str, guide_raw, t1: str | None,
                   positions: dict, equity: float,
                   scan_id, scan_kind: str, mode: str,
                   now: datetime, pc_runner,
                   snapshot_id=_OMIT) -> dict | None:
    """One (name, book) step of the crossing state machine: evaluate the
    candidate at `price`, compare to the stored state, write a crossing
    row on a transition, and save the new state. Returns the crossing
    row written, or None (no transition — or a first sighting, which
    establishes state silently: a crossing is a transition, and there
    is nothing to transition from). This is the single implementation
    of the transition logic — run_scan drives it at sheet prices on
    the scan cadence, and Spec D's level watcher drives it at intraday
    prices through run_watcher_evaluation. Same code, same row shape;
    only the price and the scan_kind stamp differ."""
    bands = sheet["bands"]
    held_mv = float((positions.get(ticker) or {}).get("mv") or 0.0)
    cand = candidate(zone=zone, guide_status=guide_status, t1=t1,
                     held_mv=held_mv, equity=equity)
    prev = _state_row(client, ticker, book)
    state = {"zone": zone, "action": cand["action"],
             "target_pct": cand["target_pct"],
             "guide_status": guide_status,
             "t1_classification": t1, "held": held_mv > 0,
             "sheet_computed_at": sheet.get("computed_at"),
             "updated_at": now.isoformat()}
    if prev is None:
        _save_state(client, ticker, book, state)
        return None
    changed = ((cand["action"], cand["target_pct"])
               != (prev.get("action"), prev.get("target_pct")))
    gated_transition = (
        zone != prev.get("zone") and cand["action"] is None
        and cand["suppress_reason"] in _GATE_REASONS)
    row = None
    if changed or gated_transition:
        reason = cand["suppress_reason"]
        if cand["action"] is None and reason is None:
            reason = "zone_exit"
        pc_outcome, pc_detail = None, None
        if cand["action"] == "review_full_exit":
            pc_outcome = "not_run"
            pc_detail = ("review flag — no would-be order; Kevin's "
                         "call, never an auto-exit")
        elif cand["action"] is not None:
            pc_outcome, pc_detail = pc_runner(
                book, ticker, cand["delta_usd"])
        payload = {
            "scan_id": scan_id, "scan_kind": scan_kind,
            "book": book, "ticker": ticker,
            "industry": industry_of(sheet),
            "band_basis": sheet.get("band_basis", "eps"),
            "bear": float(bands["bear"]),
            "base": float(bands["base"]),
            "bull": float(bands["bull"]),
            "price": price, "price_as_of": price_as_of,
            "zone": zone, "prev_action": prev.get("action"),
            "action": cand["action"] or "none",
            "target_pct": cand["target_pct"],
            "delta_usd": cand["delta_usd"],
            "held_mv": held_mv,
            "held_weight_pct": (round(held_mv / equity * 100, 4)
                                if equity > 0 else None),
            "guide_status": guide_status,
            "guide_direction": guide_raw,
            "t1_classification": t1,
            "suppress_reason": reason if cand["action"] is None
                               else None,
            "pc_outcome": pc_outcome, "pc_detail": pc_detail,
            "mode": mode,
            "created_at": now.isoformat(),
        }
        if snapshot_id is not _OMIT:
            # Provenance for the Guidance Reliability lane's persisted
            # band snapshots: watcher-stamped rows carry the snapshot
            # the bands came from (null until the snapshot compute
            # lands and sheets carry the id). Scan inserts omit the
            # key entirely — their behavior is unchanged.
            payload["snapshot_id"] = snapshot_id
        inserted = client.table(CROSSINGS).insert(payload).execute()
        row = (inserted.data or [None])[0]
    _save_state(client, ticker, book, state)
    return row


# ── the scan ─────────────────────────────────────────────────────────────────

def run_scan(client, *, kind: str, now: datetime | None = None,
             books: tuple[str, ...] = BOOKS,
             positions_reader=None, equity_reader=None,
             t1_reader=None, pc_runner=None) -> dict:
    """One scan over the latest banded sheets, per book. Writes crossing
    rows only on transitions (freeze doc: the state machine), updates
    every state row, and audits itself in band_crossing_scans. Places
    nothing — there is no order path in this module."""
    from tradehub.valuation import store as val_store

    now = now or datetime.now(timezone.utc)
    positions_reader = positions_reader or _default_positions
    equity_reader = equity_reader or _default_equity
    t1_reader = t1_reader or t1_classification
    pc_runner = pc_runner or _default_pc

    sheets = val_store.latest_sheets(client)
    state_empty = not (client.table(STATE).select("ticker").limit(1)
                       .execute().data or [])
    effective_kind = "baseline" if state_empty else kind
    mode = "log_only" if not orders_enabled(client) else "orders_enabled"

    scan_rows = (client.table(SCANS).insert({
        "kind": effective_kind, "requested_kind": kind,
        "started_at": now.isoformat(), "mode": mode}).execute().data) or []
    scan_id = scan_rows[0]["id"] if scan_rows else None

    book_cache: dict[str, tuple[dict, float] | Exception] = {}

    def book_state(book: str):
        if book not in book_cache:
            try:
                book_cache[book] = (positions_reader(book),
                                    float(equity_reader(book)))
            except Exception as exc:  # noqa: BLE001 -- named in the audit row
                book_cache[book] = exc
        return book_cache[book]

    banded = 0
    state_rows = 0
    crossings_written = 0
    skipped: list[dict] = []
    book_skips: list[dict] = []
    watermark = None

    for sheet in sheets:
        computed = sheet.get("computed_at")
        if computed and (watermark is None or str(computed) > watermark):
            watermark = str(computed)
        if sheet.get("status") != "banded" or not sheet.get("bands"):
            continue
        banded += 1
        ticker = sheet["ticker"]
        if sheet.get("stale"):
            skipped.append({"ticker": ticker, "reason": "stale_sheet"})
            continue
        price = sheet.get("price")
        if price is None:
            skipped.append({"ticker": ticker, "reason": "no_price"})
            continue
        price = float(price)
        bands = sheet["bands"]
        zone = zone_of(price, bands)
        guide_status, guide_raw = guide_status_of(sheet)
        t1 = t1_reader(client, ticker)

        for book in books:
            got = book_state(book)
            if isinstance(got, Exception):
                book_skips.append({"ticker": ticker, "book": book,
                                   "reason": f"book_unreadable: "
                                             f"{type(got).__name__}"})
                continue
            positions, equity = got
            row = _evaluate_book(
                client, sheet=sheet, ticker=ticker, book=book,
                price=price, price_as_of=sheet.get("price_as_of"),
                zone=zone, guide_status=guide_status, guide_raw=guide_raw,
                t1=t1, positions=positions, equity=equity,
                scan_id=scan_id, scan_kind=effective_kind, mode=mode,
                now=now, pc_runner=pc_runner)
            if row is not None:
                crossings_written += 1
            state_rows += 1

    summary = {"banded_names": banded, "state_rows": state_rows,
               "skipped": skipped, "book_skips": book_skips}
    if scan_id is not None:
        client.table(SCANS).update({
            "finished_at": now.isoformat(),
            "sheets_watermark": watermark, **summary}) \
            .eq("id", scan_id).execute()
    return {"kind": effective_kind, "requested_kind": kind, "mode": mode,
            "crossings_written": crossings_written, **summary}


# ── Spec D's real-time driver over this state machine ───────────────────────

def run_watcher_evaluation(client, *, prices: dict, now: datetime | None = None,
                           books: tuple[str, ...] = BOOKS,
                           positions_reader=None, equity_reader=None,
                           t1_reader=None, pc_runner=None) -> dict:
    """Evaluate banded names at INTRADAY prices (Spec D's level watcher,
    Stage 1) through the same transition step the scans run
    (_evaluate_book): crossing rows land in this log with
    scan_kind='watcher' and the state moves exactly as a scan would
    move it, so a later scan at the same zone writes no duplicate.
    Watcher rows are the same population the falsifier grades (the
    grade_crossings pass below), stamped by source so reporting can
    separate them.

    Only names present in `prices` are evaluated (the watcher passes
    the names whose live zone moved). The data-missing rules are the
    scans': a stale sheet is skipped with its state untouched. The
    watcher never establishes the baseline — with an empty state
    table this writes nothing and says so (baselining belongs to the
    scans, as frozen).

    Provenance: watcher rows also carry `snapshot_id` — the persisted
    band snapshot the sheet's bands came from (the Guidance
    Reliability lane's snapshot table), read off the sheet; null
    until that lane's compute stamps sheets with the id. Scan rows
    omit the key (their inserts are unchanged)."""
    from zoneinfo import ZoneInfo

    from tradehub.valuation import store as val_store

    now = now or datetime.now(timezone.utc)
    positions_reader = positions_reader or _default_positions
    equity_reader = equity_reader or _default_equity
    t1_reader = t1_reader or t1_classification
    pc_runner = pc_runner or _default_pc

    state_empty = not (client.table(STATE).select("ticker").limit(1)
                       .execute().data or [])
    if state_empty:
        return {"ran": False, "reason": "no_baseline",
                "crossings": [], "crossings_written": 0,
                "state_rows": 0, "skipped": [], "book_skips": []}

    mode = "log_only" if not orders_enabled(client) else "orders_enabled"
    scan_rows = (client.table(SCANS).insert({
        "kind": "watcher", "requested_kind": "watcher",
        "started_at": now.isoformat(), "mode": mode}).execute().data) or []
    scan_id = scan_rows[0]["id"] if scan_rows else None
    price_as_of = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()

    book_cache: dict[str, tuple[dict, float] | Exception] = {}

    def book_state(book: str):
        if book not in book_cache:
            try:
                book_cache[book] = (positions_reader(book),
                                    float(equity_reader(book)))
            except Exception as exc:  # noqa: BLE001 -- named in the audit row
                book_cache[book] = exc
        return book_cache[book]

    evaluated = 0
    state_rows = 0
    crossings: list[dict] = []
    skipped: list[dict] = []
    book_skips: list[dict] = []
    watermark = None

    for sheet in val_store.latest_sheets(client):
        computed = sheet.get("computed_at")
        if computed and (watermark is None or str(computed) > watermark):
            watermark = str(computed)
        if sheet.get("status") != "banded" or not sheet.get("bands"):
            continue
        ticker = sheet["ticker"]
        if ticker not in prices:
            continue
        evaluated += 1
        if sheet.get("stale"):
            skipped.append({"ticker": ticker, "reason": "stale_sheet"})
            continue
        price = float(prices[ticker])
        zone = zone_of(price, sheet["bands"])
        guide_status, guide_raw = guide_status_of(sheet)
        t1 = t1_reader(client, ticker)
        for book in books:
            got = book_state(book)
            if isinstance(got, Exception):
                book_skips.append({"ticker": ticker, "book": book,
                                   "reason": f"book_unreadable: "
                                             f"{type(got).__name__}"})
                continue
            positions, equity = got
            row = _evaluate_book(
                client, sheet=sheet, ticker=ticker, book=book,
                price=price, price_as_of=price_as_of,
                zone=zone, guide_status=guide_status, guide_raw=guide_raw,
                t1=t1, positions=positions, equity=equity,
                scan_id=scan_id, scan_kind="watcher", mode=mode,
                now=now, pc_runner=pc_runner,
                snapshot_id=sheet.get("snapshot_id"))
            if row is not None:
                crossings.append(row)
            state_rows += 1

    summary = {"banded_names": evaluated, "state_rows": state_rows,
               "skipped": skipped, "book_skips": book_skips}
    if scan_id is not None:
        client.table(SCANS).update({
            "finished_at": now.isoformat(),
            "sheets_watermark": watermark,
            "crossings_written": len(crossings), **summary}) \
            .eq("id", scan_id).execute()
    return {"ran": True, "kind": "watcher", "mode": mode,
            "crossings": crossings,
            "crossings_written": len(crossings), **summary}


# ── grading: the frozen falsifier computation ────────────────────────────────

def compute_outcome(closes, entry_date: str, horizon: int,
                    direction: int) -> dict | None:
    """One entry graded at one horizon (freeze doc, exact): the entry's
    return minus the same-name unconditional control (entries every 5th
    session over the prior 252 sessions, full windows only, >= 10
    starts), per unit of risk (the outcome window's daily-log-return
    stdev x sqrt(h)). None when the window is immature, the control is
    thin, or the window has no variance to grade against."""
    import pandas as pd

    closes = closes.dropna().sort_index()
    pos = closes.index.get_indexer([pd.Timestamp(entry_date)], method="pad")
    if len(pos) == 0 or pos[0] < 0 or pos[0] + horizon >= len(closes):
        return None
    pos = int(pos[0])
    entry = float(closes.iloc[pos])
    end = float(closes.iloc[pos + horizon])
    if entry <= 0:
        return None
    r = end / entry - 1.0

    starts = range(max(0, pos - 252), pos, 5)
    control = [float(closes.iloc[s + horizon]) / float(closes.iloc[s]) - 1.0
               for s in starts if s + horizon <= pos]
    if len(control) < 10:
        return None
    u = statistics.fmean(control)

    window = closes.iloc[pos:pos + horizon + 1]
    logs = [math.log(float(b) / float(a))
            for a, b in zip(window.iloc[:-1], window.iloc[1:])
            if float(a) > 0 and float(b) > 0]
    if len(logs) < 2:
        return None
    sigma = statistics.pstdev(logs) * math.sqrt(horizon)
    if sigma <= 0:
        return None
    return {"horizon": horizon,
            "ret_pct": round(r * 100, 4),
            "uncond_pct": round(u * 100, 4),
            "excess_pct": round((r - u) * 100, 4),
            "sigma_pct": round(sigma * 100, 4),
            "score": round(direction * (r - u) / sigma, 4),
            "control_starts": len(control)}


def falsifier_summary(rows: list[dict]) -> dict:
    """The falsifier over crossing rows: graded entries are ENTRY_ACTIONS
    rows carrying a score_20. At FALSIFIER_GATE graded entries the mean
    score decides — survived (> 0) or shelved (<= 0). Before the gate the
    status is 'accruing' and no verdict is implied."""
    graded = [r for r in rows
              if r.get("action") in ENTRY_ACTIONS
              and r.get("score_20") is not None]
    scores = [float(r["score_20"]) for r in graded]
    mean = round(statistics.fmean(scores), 4) if scores else None
    if len(graded) < FALSIFIER_GATE:
        status = "accruing"
    else:
        status = "survived" if mean is not None and mean > 0 else "shelved"
    return {"gate": FALSIFIER_GATE, "graded": len(graded),
            "mean_score": mean, "status": status}


def grade_crossings(client, ds, *, now: datetime | None = None) -> dict:
    """One grading pass: fill outcome_5 / outcome_20 (+ score_20) on
    entry crossings whose windows have matured. Idempotent — a filled
    horizon is never recomputed."""
    rows = (client.table(CROSSINGS).select("*").execute().data) or []
    entries = [r for r in rows if r.get("action") in ENTRY_ACTIONS]
    written = 0
    frames: dict[str, object] = {}
    for row in entries:
        need = [h for h in (5, 20) if row.get(f"outcome_{h}") is None]
        if not need:
            continue
        ticker = row["ticker"]
        if ticker not in frames:
            try:
                frames[ticker] = ds.prices([ticker], years=3)
            except Exception:  # noqa: BLE001 -- a failed pull defers the grade
                frames[ticker] = None
        frame = frames[ticker]
        if frame is None or ticker not in frame.columns:
            continue
        closes = frame[ticker].dropna()
        direction = -1 if row["action"] == "short_put_spread" else 1
        entry_date = str(row.get("price_as_of")
                         or str(row.get("created_at"))[:10])
        patch: dict = {}
        for h in need:
            out = compute_outcome(closes, entry_date, h, direction)
            if out is not None:
                patch[f"outcome_{h}"] = out
                if h == 20:
                    patch["score_20"] = out["score"]
        if patch:
            client.table(CROSSINGS).update(patch).eq("id", row["id"]).execute()
            written += 1
    return {"entries_seen": len(entries), "rows_graded": written}


# ── the event-scan decision ──────────────────────────────────────────────────

def sheets_watermark(client) -> str | None:
    from tradehub.valuation import store as val_store

    marks = [s.get("computed_at") for s in val_store.latest_sheets(client)]
    marks = [str(m) for m in marks if m]
    return max(marks) if marks else None


def last_scan_watermark(client) -> str | None:
    try:
        rows = (client.table(SCANS).select("sheets_watermark, finished_at")
                .order("id", desc=True).limit(5).execute().data) or []
    except Exception:  # noqa: BLE001 -- no scans yet is a first-scan case
        return None
    for row in rows:
        if row.get("finished_at") and row.get("sheets_watermark"):
            return str(row["sheets_watermark"])
    return None


def auto_decision(client) -> tuple[bool, str]:
    """The event re-scan fires only when the sheets moved since the last
    completed scan (a re-banding happened) — or when no scan has ever
    completed (the baseline is still owed)."""
    last = last_scan_watermark(client)
    if last is None:
        return True, "no completed scan yet — the baseline is owed"
    current = sheets_watermark(client)
    if current is not None and current > last:
        return True, f"sheets advanced past the last scan ({last} -> {current})"
    return False, "sheets unchanged since the last completed scan"


# ── the read surface ─────────────────────────────────────────────────────────

def read_surface(client, *, limit: int = 50) -> dict:
    """The Guidance page's crossings payload: the mode up front (never
    implied), the falsifier counter, recent scans, recent crossings."""
    enabled = orders_enabled(client)
    crossings: list[dict] = []
    scans: list[dict] = []
    try:
        crossings = (client.table(CROSSINGS).select("*")
                     .order("id", desc=True).limit(limit)
                     .execute().data) or []
    except Exception:  # noqa: BLE001 -- pre-migration reads as an empty log
        crossings = []
    try:
        scans = (client.table(SCANS).select("*")
                 .order("id", desc=True).limit(5).execute().data) or []
    except Exception:  # noqa: BLE001
        scans = []
    all_rows = crossings
    if len(crossings) >= limit:  # the falsifier counts every entry, not a page
        try:
            all_rows = (client.table(CROSSINGS)
                        .select("action, score_20").execute().data) or []
        except Exception:  # noqa: BLE001
            all_rows = crossings
    return {"mode": "orders_enabled" if enabled else "log_only",
            "orders_enabled": enabled,
            "falsifier": falsifier_summary(all_rows),
            "scans": scans,
            "crossings": crossings}
