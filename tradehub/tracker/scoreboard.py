"""Thesis tracker PR 7 — the scoreboard read model (design
docs/superpowers/specs/2026-11-16-thesis-tracker-design.md,
"Scoreboard page"): GET /api/thesis/scoreboard renders this dict.

- Per claim (thesis_falsifiers A/B/C): graded count, hit rate with a
  Wilson interval, the falsifier countdown (prints / fires / clusters
  remaining, days to deadline), and the persisted state. Claim A and
  C progress is computed by the SAME pure functions the grader uses
  (grading.claim_a_progress / claim_c_progress) over the same inputs,
  so the board can never disagree with the grader about where a
  claim stands; the falsifier row's state stays the persisted truth
  and the progress verdict rides along as a separate field. Claim B
  is display-only: its clusters are the 2027 hyperscaler print
  rounds, no cluster record exists yet, so the board shows the
  window and the countdown from the falsifier row alone.
- Per play kind: P&L net of costs and hit rate from
  links.pnl_by_play_kind (PR 5's FIFO join) — kinds reported
  separately, never blended. The two pre-print signals (whisper,
  money flow) get their own hit rates from forecast_outcomes,
  likewise never combined.
- Breach log: the machine API's persisted refusal events from the
  order routes (api_key_events, outcome refused:* — cash-floor
  blocks are the ones whose detail names the cash floor) plus the
  stale research files (a decision logged after the file's last
  amendment — the design's staleness definition).
- Regime panel: the regime_inputs registry verbatim where it
  matters — Gray Area odds, the big-four 2027 capex figure graded
  against the frozen $620B / $950B lines when a figure has been
  recorded, crash-trigger states, the three credit lights with
  as_of ages — plus the cash-floor gauge (each book's live cash
  share against tracker_config's floor).

Reads are fail-soft where a source is an external account: an
unreadable book drops out of the fire walk and the P&L (the grade
run's rule) and shows a null cash share rather than failing the
board.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from tradehub.tracker import grading, links, sizing

FALSIFIERS = "thesis_falsifiers"
THESES = "theses"
CARDS = "forecast_cards"
OUTCOMES = "forecast_outcomes"
EVENTS = "api_key_events"
RESEARCH_FILES = "research_files"
REGIME_INPUTS = "regime_inputs"
HEALTH = "tracker_health"

REFUSAL_LIMIT = 25
_EVENT_PAGE = 200
_EVENT_PAGES = 5
CREDIT_LIGHTS = (
    ("credit_light_dc_yields", "Data-center borrowing yields"),
    ("credit_light_redemption_gates", "Private-credit redemption gates"),
    ("credit_light_bank_lending", "Bank lending tightening"),
)
_CAPEX_FIGURE_KEYS = ("usd_bn", "current_usd_bn", "capex_usd_bn",
                      "figure_usd_bn", "value_usd_bn", "value")


def wilson_interval(hits: int, n: int, z: float = 1.96) -> list | None:
    """The Wilson score interval for a hit rate — the honest band
    around a small-sample rate. None when nothing is graded."""
    if not n:
        return None
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - margin), 4),
            round(min(1.0, centre + margin), 4)]


def _ts(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(
        tzinfo=timezone.utc)


def _rows(client, table, cols="*"):
    return (client.table(table).select(cols).execute().data) or []


def _signal_block(outcomes: list[dict], field: str) -> dict:
    graded = [o for o in outcomes if o.get(field) is not None]
    hits = sum(1 for o in graded if o[field])
    n = len(graded)
    return {"graded": n, "hits": hits,
            "rate": round(hits / n, 4) if n else None,
            "interval": wilson_interval(hits, n)}


def _claim_block(row: dict, thesis_slug, *, now: datetime,
                 a_rows=None, fire_nets=None) -> dict:
    deadline = row.get("deadline")
    days = None
    if deadline:
        try:
            days = (datetime.fromisoformat(str(deadline)).date()
                    - now.date()).days
        except ValueError:
            days = None
    block = {"claim": row.get("claim"), "thesis_slug": thesis_slug,
             "metric": row.get("metric"), "state": row.get("state"),
             "deadline": str(deadline) if deadline else None,
             "days_to_deadline": days,
             "threshold": row.get("threshold") or {},
             "window_spec": row.get("window_spec") or {}}
    window = block["window_spec"]
    threshold = block["threshold"]
    if row.get("claim") == "A":
        p = grading.claim_a_progress(
            a_rows or [],
            prints=int(window.get("prints", 40)),
            rolling=int(window.get("rolling_kill_prints", 60)),
            min_separation=float(threshold.get("min_separation", 0.60)),
            kill_below=float(threshold.get("kill_below_rolling", 0.50)))
        block.update({
            "graded": p["graded"], "hits": p["hits"],
            "rate": (round(p["separation"], 4)
                     if p["separation"] is not None else None),
            "interval": wilson_interval(p["hits"], p["graded"]),
            "window_separation": p["window_separation"],
            "rolling60_separation": p["rolling60_separation"],
            "prints_target": int(window.get("prints", 40)),
            "prints_remaining": p["prints_remaining"],
            "progress_verdict": p["verdict"]})
    elif row.get("claim") == "B":
        clusters = int(window.get("clusters", 4))
        block.update({
            "graded": 0, "hits": None, "rate": None, "interval": None,
            "clusters_target": clusters, "clusters_graded": 0,
            "clusters_remaining": clusters, "mean_excess": None,
            "progress_verdict": None,
            "note": ("Clusters are the 2027 hyperscaler print rounds; "
                     "none has completed, so there is nothing to grade "
                     "yet.")})
    elif row.get("claim") == "C":
        fires = int(window.get("fires", 5))
        nets = list(fire_nets or [])
        p = grading.claim_c_progress(nets, fires=fires)
        block.update({
            "graded": min(len(nets), fires), "hits": None,
            "rate": None, "interval": None,
            "fires_target": fires,
            "fires_remaining": max(0, fires - len(nets)),
            "net": p["net"], "progress_verdict": p["verdict"]})
    return block


def _regime_block(rows: list[dict], *, now: datetime) -> dict:
    by_key = {r.get("key"): r for r in rows}

    def _age(row):
        as_of = _ts((row or {}).get("as_of"))
        if as_of is None:
            return None
        return round((now - as_of).total_seconds() / 86400, 1)

    odds_row = by_key.get("gray_area_odds") or {}
    odds_detail = odds_row.get("detail") or {}
    odds = {"state": odds_row.get("state"),
            "stalemate": odds_detail.get("stalemate"),
            "boom": odds_detail.get("boom"),
            "crash": odds_detail.get("crash"),
            "as_of": odds_row.get("as_of"),
            "source_note": odds_row.get("source_note")}

    capex_row = by_key.get("big4_capex_2027") or {}
    capex_detail = capex_row.get("detail") or {}
    crash_below = capex_detail.get("crash_below_usd_bn", 620)
    boom_at = capex_detail.get("boom_at_or_above_usd_bn", 950)
    figure = None
    for key in _CAPEX_FIGURE_KEYS:
        value = capex_detail.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            figure = float(value)
            break
    grading_state = None
    if figure is not None:
        grading_state = ("crash" if figure < crash_below
                         else "boom" if figure >= boom_at else "between")
    capex = {"figure_usd_bn": figure,
             "crash_below_usd_bn": crash_below,
             "boom_at_or_above_usd_bn": boom_at,
             "grading": grading_state,
             "state": capex_row.get("state"),
             "as_of": capex_row.get("as_of"),
             "source_note": capex_row.get("source_note")}

    triggers_row = by_key.get("crash_triggers") or {}
    fired = (triggers_row.get("detail") or {}).get("fired") or []
    triggers = {"fired": fired, "fired_count": len(fired),
                "state": triggers_row.get("state"),
                "as_of": triggers_row.get("as_of"),
                "source_note": triggers_row.get("source_note")}

    lights = []
    for key, label in CREDIT_LIGHTS:
        row = by_key.get(key) or {}
        lights.append({"key": key, "label": label,
                       "state": row.get("state", "unknown"),
                       "as_of": row.get("as_of"),
                       "age_days": _age(row),
                       "source_note": row.get("source_note")})
    return {"odds": odds, "capex": capex, "crash_triggers": triggers,
            "credit_lights": lights,
            "inputs": [{"key": r.get("key"), "state": r.get("state"),
                        "detail": r.get("detail") or {},
                        "as_of": r.get("as_of"),
                        "source_note": r.get("source_note")}
                       for r in rows]}


def _refusals(client) -> list[dict]:
    """The newest REFUSAL_LIMIT refused:* audit events from the
    order routes (place + preflight — the preflight blocks this log
    exists for; auth refusals on other routes are not breaches),
    newest first. Paged newest-first so a long audit history cannot
    hide the recent blocks behind the response cap."""
    out: list[dict] = []
    for page in range(_EVENT_PAGES):
        rows = (client.table(EVENTS).select("*")
                .order("at", desc=True)
                .range(page * _EVENT_PAGE, page * _EVENT_PAGE
                       + _EVENT_PAGE - 1)
                .execute().data) or []
        for row in rows:
            outcome = str(row.get("outcome") or "")
            if not outcome.startswith("refused:"):
                continue
            if "/orders" not in str(row.get("route") or ""):
                continue
            detail = row.get("detail") or ""
            out.append({"at": row.get("at"), "route": row.get("route"),
                        "outcome": outcome, "detail": detail,
                        "key_id": row.get("key_id"),
                        "client_order_id": row.get("client_order_id"),
                        "cash_floor": "cash floor" in detail.lower()})
            if len(out) >= REFUSAL_LIMIT:
                return out
        if len(rows) < _EVENT_PAGE:
            break
    return out


def _stale_files(client, theses_by_id: dict) -> list[dict]:
    """A research file is stale when a decision was logged after its
    last amendment (the design's definition)."""
    out = []
    for row in _rows(client, RESEARCH_FILES):
        decided = _ts(row.get("last_decision_at"))
        if decided is None:
            continue
        amended = _ts(row.get("amended_at"))
        if amended is not None and decided <= amended:
            continue
        thesis = theses_by_id.get(row.get("thesis_id")) or {}
        out.append({"path": row.get("path"),
                    "thesis_slug": thesis.get("slug"),
                    "amended_at": row.get("amended_at"),
                    "last_decision_at": row.get("last_decision_at")})
    return out


def _default_book_state(client) -> dict:
    """The grade run's FIFO book state, built by its own builder so
    the board and the grader can never read different books."""
    from tradehub.scripts.thesis_grade_run import book_state
    return book_state(client)


def _default_account(book: str) -> dict | None:
    try:
        from tradehub.portfolio.alpaca_paper import paper_get
        return paper_get("/v2/account", book=book)
    except Exception:  # noqa: BLE001 -- an unreadable book shows null
        return None


def _cash_gauge(floor_pct: float, *, account_fn) -> dict:
    from tradehub.portfolio import books
    out = []
    for name in books.names():
        account = account_fn(name)
        cash_pct = None
        if account:
            try:
                equity = float(account.get("portfolio_value")
                               or account.get("equity") or 0)
                cash = float(account.get("cash") or 0)
                if equity > 0:
                    cash_pct = round(100.0 * cash / equity, 2)
            except (TypeError, ValueError):
                cash_pct = None
        out.append({"book": name, "cash_pct": cash_pct,
                    "breach": (cash_pct is not None
                               and cash_pct < floor_pct)})
    return {"floor_pct": floor_pct, "books": out}


def build_scoreboard(client, *, now: datetime | None = None,
                     book_state: dict | None = None,
                     account_fn=None) -> dict:
    """The whole board as one dict. `book_state` and `account_fn`
    are injected by tests; production builds the grade run's book
    state and reads each book's Alpaca account, both fail-soft."""
    now = now or datetime.now(timezone.utc)
    theses = _rows(client, THESES)
    theses.sort(key=lambda r: r.get("id") or 0)
    theses_by_id = {r.get("id"): r for r in theses}
    falsifiers = _rows(client, FALSIFIERS)
    falsifiers.sort(key=lambda r: (str(r.get("claim") or ""),
                                   r.get("id") or 0))
    outcomes = _rows(client, OUTCOMES)
    cards = _rows(client, CARDS)
    by_card = {r["id"]: r for r in cards}
    graded = [o for o in outcomes if o.get("card_id") in by_card]
    graded.sort(key=lambda o: (str(by_card[o["card_id"]].get("print_at")
                                   or ""), o.get("id") or 0))
    a_rows = [{"classification_hit": o.get("classification_hit")}
              for o in graded]

    if book_state is None:
        book_state = _default_book_state(client)
    fire_nets = links.claim_c_fire_nets(client, book_state, now=now)
    play_kinds = {}
    for kind, slot in links.pnl_by_play_kind(client, book_state).items():
        trades = slot["trades"]
        play_kinds[kind] = {
            **slot,
            "hit_rate": (round(slot["wins"] / trades, 4)
                         if trades else None),
            "interval": wilson_interval(slot["wins"], trades)}

    config = sizing.load_config(client)
    health_rows = _rows(client, HEALTH)
    health = health_rows[0] if health_rows else {}
    regime_rows = _rows(client, REGIME_INPUTS)

    return {
        "generated_at": now.isoformat(),
        "theses": [{"slug": t.get("slug"), "title": t.get("title"),
                    "sleeve": t.get("sleeve"), "status": t.get("status"),
                    "kill_line_count": len(t.get("kill_lines") or []),
                    "spec_ref": t.get("spec_ref")} for t in theses],
        "claims": [_claim_block(
            row, (theses_by_id.get(row.get("thesis_id")) or {}).get("slug"),
            now=now, a_rows=a_rows, fire_nets=fire_nets)
            for row in falsifiers],
        "signals": {
            "whisper": _signal_block(graded, "whisper_hit"),
            "money_flow": _signal_block(graded, "money_flow_hit")},
        "play_kinds": play_kinds,
        "sizing": {"config": config,
                   "health": {
                       "last_grader_run_at": health.get(
                           "last_grader_run_at"),
                       "last_grader_ok": bool(health.get(
                           "last_grader_ok"))},
                   "governing_unit": sizing.governing_unit(client,
                                                           now=now)},
        "regime": _regime_block(regime_rows, now=now),
        "cash_gauge": _cash_gauge(float(config["cash_floor_pct"]),
                                  account_fn=account_fn
                                  or _default_account),
        "breaches": {"refusals": _refusals(client),
                     "stale_files": _stale_files(client, theses_by_id)},
    }
