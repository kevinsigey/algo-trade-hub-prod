"""Debate candidates (Loop Batch 2, charter workstream 4): which names get
a valuation debate, and why — generated from the screening/guidance flow.

Three source classes, in frozen priority order:
  1. CONJUNCTIONS — a recorded screen survivor sitting in a directional
     band zone with a recent print classification on record: three
     independent systems point at the same name.
  2. BAND ZONES — strong zones first (buy_zone_strong / short_zone_strong),
     then plain directional zones, off the latest COMPLETED snapshot's
     persisted band history (never a live recompute).
  3. ENTRANTS — names that entered a diffed screen recently (the recorded
     membership events), whether or not they carry a zone.

HARD CONSTRAINT (Round 2 verification finding): candidate generation
reads RECORDED screen runs and membership only — the screens table's
stored last_run / membership / membership_events. Ad-hoc builder runs
never write those fields, so they can never mint a candidate. A name
that cannot debate (no sheet in the snapshot, unbanded, stale) is named
in `excluded` with its reason — never silently dropped, never proxied
(scar tissue #8), and every candidate row carries the exhibit snapshot
id it was generated against (scar tissue #9).

Display-only, like the rest of the valuation layer: candidates queue
debates; verdicts never feed ideas, books, or orders.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradehub.valuation import store as val_store

CANDIDATES = "debate_candidates"
STRONG_ZONES = ("buy_zone_strong", "short_zone_strong")
DIRECTIONAL_ZONES = ("buy_zone", "short_zone") + STRONG_ZONES
ENTRANT_WINDOW_DAYS = 31     # an entrance is "recent" inside a month
PRINT_RECENT_DAYS = 60       # a print classification is "recent" inside 60d
TRIGGER_FOR_CLASS = {"conjunction": "conjunction",
                     "entrant": "screen_entrant", "zone": "band_zone"}
_MISSING_TABLE = ("does not exist", "42P01", "PGRST205", "schema cache")


def _parse_day(value):
    """The calendar day (a date) of an ISO date/datetime string, or None.
    Recency windows in this module are day-grained, so all comparisons
    happen in date space — never naive-vs-aware datetime arithmetic."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


# ── print classifications (the T1 provider contract, read with its date) ────

def print_classification(client, ticker: str) -> dict | None:
    """{classification, as_of} from the forward-file classifications
    table, latest row wins — or None when no source exists for the name.
    Same provider contract as band_crossing.t1_classification, read with
    its as-of so 'recent' is a checkable fact, not an assumption."""
    from tradehub.valuation.band_crossing import T1_TABLE

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
    if value not in ("improved", "intact", "deteriorated"):
        return None
    return {"classification": value, "as_of": rows[0].get("as_of")}


# ── recorded screen context ─────────────────────────────────────────────────

def screen_contexts(client, *, now: datetime) -> dict[str, dict]:
    """Per-ticker recorded screen context from the screens table ONLY:
    current memberships (with since-dates), recent entrances, and whether
    the name survived any screen's recorded last run. Ad-hoc builder runs
    write none of these fields, by construction."""
    try:
        rows = (client.table("screens").select("*").execute().data) or []
    except Exception:  # noqa: BLE001 -- no screens table: no screen context
        rows = []
    out: dict[str, dict] = {}
    horizon = now.date() - timedelta(days=ENTRANT_WINDOW_DAYS)
    tomorrow = now.date() + timedelta(days=1)
    for row in rows:
        membership = row.get("membership") or {}
        members = membership.get("members") or {}
        survivors = {(s or "").strip().upper()
                     for s in ((row.get("last_run") or {}).get("survivors")
                               or [])}
        entrants: dict[str, str] = {}
        for event in row.get("membership_events") or []:
            if event.get("kind") != "entered":
                continue
            day = _parse_day(event.get("date"))
            if day is None or day < horizon or day > tomorrow:
                continue
            for t in event.get("tickers") or [event.get("ticker")]:
                if t:
                    entrants[str(t).strip().upper()] = event["date"]
        for ticker in set(members) | survivors | set(entrants):
            ctx = out.setdefault(ticker, {"screens": [], "entrants": [],
                                          "survivor": False})
            ctx["screens"].append({
                "screen_id": row.get("id"), "screen_name": row.get("name"),
                "member_since": members.get(ticker),
                "in_last_run": ticker in survivors})
            if ticker in members or ticker in survivors:
                ctx["survivor"] = True
            if ticker in entrants:
                ctx["entrants"].append({
                    "screen_id": row.get("id"),
                    "screen_name": row.get("name"),
                    "date": entrants[ticker]})
    return out


# ── held positions (the ranking signal for conjunctions) ────────────────────

BOOKS = ("main", "big")


def _sleeve_map(client) -> dict[str, list[str]]:
    """ticker -> thesis sleeve labels from the Portfolio Check config —
    the hub's maintained thesis map (the t8_ai sleeve is the T8 AI
    winners core). Read live so a config edit retunes the tags."""
    try:
        from tradehub.portfolio.portfolio_check import load_config

        config = load_config(client)
    except Exception:  # noqa: BLE001 -- no config: no sleeve tags
        return {}
    out: dict[str, list[str]] = {}
    for sleeve in (config.get("sleeves") or {}).values():
        for symbol in sleeve.get("symbols") or []:
            out.setdefault(str(symbol).upper(), []).append(
                sleeve.get("label"))
    return out


def held_positions(client, positions_fn=None) -> dict | None:
    """{ticker: {books, qty, sleeves}} for names held in either book,
    read through the hub's existing portfolio read (positions_map over
    both books; option positions map to their underlying). None when
    the read is unavailable — ranking then falls back to plain class
    order and the generation output says so; never guessed."""
    if positions_fn is None:
        def positions_fn(book):  # noqa: F811 -- the real book read
            from tradehub.portfolio.option_orders import positions_map

            return positions_map(book)
    try:
        from tradehub.valuation.watch import underlying

        sleeves = _sleeve_map(client)
        out: dict[str, dict] = {}
        for book in BOOKS:
            for symbol, qty in (positions_fn(book) or {}).items():
                if not qty:
                    continue
                ticker = underlying(str(symbol).upper())
                entry = out.setdefault(ticker, {
                    "books": [], "qty": 0.0,
                    "sleeves": sleeves.get(ticker, [])})
                if book not in entry["books"]:
                    entry["books"].append(book)
                entry["qty"] += float(qty)
        return out
    except Exception:  # noqa: BLE001 -- unavailable is a stated fallback
        return None


# ── generation ──────────────────────────────────────────────────────────────

def _priority(candidate_class: str, zone: str | None) -> int:
    if candidate_class == "conjunction":
        return 10
    if zone in STRONG_ZONES:
        return 20
    if candidate_class == "entrant":
        return 30
    return 40


def generate_candidates(client, *, now: datetime | None = None,
                        positions_fn=None) -> dict:
    """One generation pass over the latest completed snapshot + the
    recorded screens. Persists new pending rows (idempotent per snapshot:
    a ticker with any candidate row for this snapshot is not re-queued)
    and returns the full picture — candidates, exclusions with reasons,
    and counts by source class. Held-thesis overlap (a name the books
    actually hold, T8 core/satellite first among them) is a RANKING
    signal for conjunctions and recorded context on every candidate —
    it never creates a candidate by itself."""
    now = now or datetime.now(timezone.utc)
    snap = val_store.latest_snapshot(client)
    if snap is None:
        return {"snapshot": None, "generated_at": now.isoformat(),
                "counts": {"entrants": 0, "zone_names": 0, "conjunctions": 0,
                           "held_conjunctions": 0,
                           "total": 0, "excluded": 0},
                "held_positions_unavailable": False,
                "candidates": [], "excluded": [], "inserted": 0}
    held = held_positions(client, positions_fn)
    snapshot_id = snap["id"]
    sheets = {s["ticker"]: s
              for s in val_store.snapshot_sheets(client, snapshot_id)}
    zones = {r["ticker"]: r.get("zone")
             for r in val_store.snapshot_history(client, snapshot_id)}
    contexts = screen_contexts(client, now=now)

    considered = set(sheets) | set(contexts)
    candidates: list[dict] = []
    excluded: list[dict] = []
    for ticker in sorted(considered):
        sheet = sheets.get(ticker)
        if sheet is None:
            excluded.append({"ticker": ticker, "reason":
                             f"no fact sheet in snapshot #{snapshot_id}"})
            continue
        if sheet.get("status") != "banded" or not sheet.get("bands"):
            excluded.append({"ticker": ticker, "reason":
                             f"no bands — sheet status "
                             f"{sheet.get('status')}"})
            continue
        if sheet.get("stale"):
            excluded.append({"ticker": ticker, "reason":
                             "fact sheet is stale — a stale sheet does "
                             "not debate"})
            continue
        ctx = contexts.get(ticker) or {"screens": [], "entrants": [],
                                       "survivor": False}
        zone = zones.get(ticker) or sheet.get("baseline_verdict")
        zone = zone if zone in DIRECTIONAL_ZONES else None
        print_ctx = print_classification(client, ticker)
        print_recent = False
        if print_ctx is not None:
            as_of = _parse_day(print_ctx.get("as_of"))
            print_recent = as_of is not None and \
                as_of >= now.date() - timedelta(days=PRINT_RECENT_DAYS)
        conjunction = bool(ctx["survivor"] and zone and print_recent)
        if conjunction:
            candidate_class = "conjunction"
        elif ctx["entrants"]:
            candidate_class = "entrant"
        elif zone:
            candidate_class = "zone"
        else:
            excluded.append({"ticker": ticker, "reason":
                             "no directional zone and no recorded screen "
                             "link"})
            continue
        sources = {
            "screens": ctx["screens"],
            "memberships": [s for s in ctx["screens"]
                            if s.get("member_since")],
            "entrants": ctx["entrants"],
            "zone": zone,
            "print_classification": print_ctx,
        }
        held_ctx = (held or {}).get(ticker)
        if held_ctx:
            sources["held"] = held_ctx
        priority = _priority(candidate_class, zone)
        if held_ctx and candidate_class == "conjunction":
            # Screen x zone x print AND held in the books: the proven
            # conjunction shape drains ahead of unheld conjunctions.
            priority = 5
        candidates.append({
            "ticker": ticker, "snapshot_id": snapshot_id,
            "candidate_class": candidate_class,
            "priority": priority,
            "state": "pending",
            "sources": sources,
            "computed_at": now.isoformat()})
    candidates.sort(key=lambda r: (r["priority"], r["ticker"]))

    existing = set()
    try:
        existing = {r["ticker"] for r in
                    (client.table(CANDIDATES).select("ticker")
                     .eq("snapshot_id", snapshot_id).execute().data) or []}
    except Exception as exc:  # noqa: BLE001 -- pre-migration: say so plainly
        if not any(m in str(exc) for m in _MISSING_TABLE):
            raise
    inserted = 0
    for row in candidates:
        if row["ticker"] in existing:
            continue
        client.table(CANDIDATES).insert(row).execute()
        inserted += 1

    counts = {
        "entrants": sum(1 for r in candidates if r["sources"]["entrants"]),
        "zone_names": sum(1 for r in candidates if r["sources"]["zone"]),
        "conjunctions": sum(1 for r in candidates
                            if r["candidate_class"] == "conjunction"),
        "held_conjunctions": sum(
            1 for r in candidates
            if r["candidate_class"] == "conjunction"
            and r["sources"].get("held")),
        "total": len(candidates), "excluded": len(excluded)}
    return {"snapshot": {"id": snapshot_id,
                         "computed_at": snap.get("computed_at")},
            "generated_at": now.isoformat(), "counts": counts,
            "held_positions_unavailable": held is None,
            "candidates": candidates, "excluded": excluded,
            "inserted": inserted}


def pending_candidates(client) -> list[dict]:
    try:
        return (client.table(CANDIDATES).select("*").eq("state", "pending")
                .order("priority").order("ticker").execute().data) or []
    except Exception as exc:  # noqa: BLE001 -- pre-migration reads as empty
        if any(m in str(exc) for m in _MISSING_TABLE):
            return []
        raise


def candidates_for_snapshot(client, snapshot_id) -> list[dict]:
    try:
        return (client.table(CANDIDATES).select("*")
                .eq("snapshot_id", snapshot_id)
                .order("priority").order("ticker").execute().data) or []
    except Exception as exc:  # noqa: BLE001
        if any(m in str(exc) for m in _MISSING_TABLE):
            return []
        raise


def _mark(client, candidate_id: int, state: str, *,
          verdict_id: int | None = None, detail: dict | None = None) -> None:
    update: dict = {"state": state}
    if verdict_id is not None:
        update["verdict_id"] = verdict_id
    if detail is not None:
        update["detail"] = detail
    client.table(CANDIDATES).update(update).eq("id", candidate_id).execute()


# ── the drain: candidates become debates ────────────────────────────────────

def run_candidate_debates(client, ds, *, chat=None, seat=None,
                          now: datetime | None = None) -> list[dict]:
    """Render pending candidates in priority order through the existing
    verdict path (shared daily budget, Exhibit A discipline, fail-closed
    LLM chain). A capacity decline (llm/seat unavailable) leaves the
    candidate pending and stops the pass — the queue retries next time;
    a structural decline (sheet moved on) marks it skipped with the
    reason. Nothing here invents a verdict."""
    from tradehub.valuation import verdicts

    now = now or datetime.now(timezone.utc)
    results: list[dict] = []
    for cand in pending_candidates(client):
        result = verdicts.render_verdict(
            client, ds, cand["ticker"],
            trigger=TRIGGER_FOR_CLASS[cand["candidate_class"]],
            chat=chat, seat=seat, now=now,
            candidate_sources=cand.get("sources"))
        results.append({**result, "candidate_id": cand["id"],
                        "candidate_class": cand["candidate_class"]})
        status = result["status"]
        if status in ("rendered", "void"):
            row = result.get("verdict_row") or {}
            _mark(client, cand["id"], status, verdict_id=row.get("id"),
                  detail={"render_status": status})
        elif status == "cap_reached":
            break
        elif status in ("llm_unavailable", "seat_unavailable"):
            _mark(client, cand["id"], "pending",
                  detail={"last_attempt": now.isoformat(),
                          "reason": result.get("reason")})
            break
        else:
            _mark(client, cand["id"], "skipped",
                  detail={"reason": result.get("reason")})
    return results
