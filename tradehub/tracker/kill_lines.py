"""Thesis tracker PR 6 — the kill-line bridge (design
docs/superpowers/specs/2026-11-16-thesis-tracker-design.md, Enforcement
points): each thesis's kill_lines materialize as level_watches rows
tagged with the thesis; when the watcher fires one, the bridge creates
ONE open manual action kind=exit_review, deduped per kill line — the
NVDA 2026-11-12 case (kill lines fired, no exit review created)
becomes structurally impossible.

Kill-line shape (defined here; theses.kill_lines is a jsonb list):
    {"symbol": "NVDA", "level": 159.0, "direction": "below",
     "note": "159 support break"}
`direction` is "below" (default — fires when price crosses DOWN
through the level, the stop-like case) or "above" (cross_up). Entries
without a usable symbol or a positive level are skipped and counted,
never armed half-formed.

Materialization is a SYNC, run on every watcher-runner invocation:
- a line on a live / shadow / demoted thesis arms a watch (family
  "thesis_kill_line", intent alert, rung 1) whose conditions carry
  the thesis id + slug and the line's stable key
  ("SYMBOL@LEVEL:direction");
- a bridge watch whose line left the thesis (edited out, or the
  thesis was killed / merged) is disabled, so kill_lines stays the
  source of truth;
- a watch that already carries the line's identity is never
  duplicated; a disabled one whose line came back is re-enabled.

Exit reviews: the bridge scans watcher_fires for this family's fires
from the last FIRE_WINDOW_DAYS. A fire opens an exit_review action —
through workshop store.add_manual_action, the same path as every
other review — in each book where the symbol is currently held
(nothing held, nothing to exit, no action). Dedupe is per kill line
and keyed on persisted markers in the action detail, the guidance
bridge's discipline: the line marker blocks while ANY exit_review
for that line is still open (one open review per kill line), and the
fire marker means a resolved line reviews again only on a NEW fire.
Resolving or dismissing an action therefore never re-opens the same
fire on a replay.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradehub.valuation import candidates as cand
from tradehub.workshop import store as workshop_store

FAMILY = "thesis_kill_line"
ACTION_KIND = "exit_review"
SOURCE = "thesis_kill_lines"
ARMED_STATUSES = {"live", "shadow", "demoted"}
FIRE_WINDOW_DAYS = 7


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_lines(thesis: dict) -> tuple[list[dict], int]:
    """(valid kill lines, invalid count) for one thesis row. A valid
    line: {symbol (upper), level (float > 0), direction, note, key}."""
    out: list[dict] = []
    invalid = 0
    raw = thesis.get("kill_lines")
    if raw is None:
        return out, invalid
    if not isinstance(raw, list):
        return out, 1
    for entry in raw:
        if not isinstance(entry, dict):
            invalid += 1
            continue
        symbol = str(entry.get("symbol") or "").strip().upper()
        level = _num(entry.get("level"))
        direction = str(entry.get("direction") or "below").strip().lower()
        if not symbol or level is None or level <= 0 \
                or direction not in ("below", "above"):
            invalid += 1
            continue
        out.append({"symbol": symbol, "level": level,
                    "direction": direction,
                    "note": str(entry.get("note") or "").strip(),
                    "key": f"{symbol}@{level:g}:{direction}"})
    return out, invalid


def _family_watches(client) -> list[dict]:
    return (client.table("level_watches")
            .select("id, instrument, level, enabled, conditions")
            .eq("family", FAMILY).execute().data) or []


def _watch_identity(row: dict) -> tuple | None:
    conds = row.get("conditions") or {}
    if conds.get("source") != SOURCE:
        return None
    return (conds.get("thesis_id"), conds.get("kill_line"))


def sync_watches(client, *, now: datetime | None = None) -> dict:
    """Materialize theses.kill_lines as level_watches rows (and
    disable bridge watches whose line is gone). Returns counts."""
    now = now or datetime.now(timezone.utc)
    theses = (client.table("theses")
              .select("id, slug, title, status, kill_lines")
              .execute().data) or []
    desired: dict[tuple, tuple[dict, dict]] = {}
    invalid = 0
    for thesis in theses:
        lines, bad = parse_lines(thesis)
        invalid += bad
        if thesis.get("status") not in ARMED_STATUSES:
            continue
        for line in lines:
            desired[(thesis.get("id"), line["key"])] = (thesis, line)
    armed = reenabled = disabled = 0
    existing = _family_watches(client)
    seen: set[tuple] = set()
    for row in existing:
        identity = _watch_identity(row)
        if identity is None:
            continue
        seen.add(identity)
        enabled = row.get("enabled") in (None, True)
        if identity in desired:
            if not enabled:
                (client.table("level_watches")
                 .update({"enabled": True,
                          "updated_at": now.isoformat()})
                 .eq("id", row["id"]).execute())
                reenabled += 1
        elif enabled:
            (client.table("level_watches")
             .update({"enabled": False,
                      "updated_at": now.isoformat()})
             .eq("id", row["id"]).execute())
            disabled += 1
    for (thesis_id, _key), (thesis, line) in desired.items():
        if (thesis_id, line["key"]) in seen:
            continue
        client.table("level_watches").insert({
            "name": f"{line['symbol']} kill line — {thesis.get('slug')}",
            "family": FAMILY, "kind": "level",
            "instrument": line["symbol"],
            "trigger_type": ("cross_down" if line["direction"] == "below"
                             else "cross_up"),
            "level": line["level"],
            "intent": "alert", "rung": 1, "book": None,
            "conditions": {"source": SOURCE,
                           "thesis_id": thesis.get("id"),
                           "thesis_slug": thesis.get("slug"),
                           "kill_line": line["key"]},
            "note": (f"Thesis kill line ({thesis.get('slug')}): "
                     f"{line['note'] or 'no note recorded'}. "
                     f"Alert only — a fire opens an exit review, "
                     f"never an order."),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }).execute()
        armed += 1
    return {"armed": armed, "reenabled": reenabled, "disabled": disabled,
            "skipped_invalid": invalid, "theses": len(theses)}


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(
        tzinfo=timezone.utc)


def open_exit_reviews(client, *, now: datetime | None = None,
                      positions_fn=None) -> dict:
    """Open one deduped exit_review action per held book for each
    recent kill-line fire that has not produced one yet."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=FIRE_WINDOW_DAYS)
    fires = (client.table("watcher_fires")
             .select("id, watch_id, instrument, fired_at, trigger_price,"
                     " level")
             .eq("family", FAMILY).execute().data) or []
    recent = [f for f in fires
              if (_parse_ts(f.get("fired_at")) or now) >= cutoff]
    recent.sort(key=lambda f: _parse_ts(f.get("fired_at")) or now)
    if not recent:
        return {"fires_seen": 0, "actions_opened": 0,
                "held_unavailable": False}
    watches = {w["id"]: w for w in _family_watches(client)}
    held = cand.held_positions(client, positions_fn)
    if held is None:
        return {"fires_seen": len(recent), "actions_opened": 0,
                "held_unavailable": True}
    opened = 0
    for fire in recent:
        watch = watches.get(fire.get("watch_id")) or {}
        conds = watch.get("conditions") or {}
        if conds.get("source") != SOURCE:
            continue
        symbol = fire.get("instrument")
        books = (held.get(symbol) or {}).get("books") or []
        if not books:
            continue  # nothing held — nothing to exit
        slug = conds.get("thesis_slug")
        line_marker = f"[kill line {slug}:{conds.get('kill_line')}]"
        fire_marker = f"[kill-line fire {fire.get('id')}]"
        rows = (client.table("manual_actions")
                .select("id, book, state, detail")
                .eq("kind", ACTION_KIND).eq("symbol", symbol)
                .is_("idea_id", "null")
                .execute().data) or []
        if any(fire_marker in (r.get("detail") or "") for r in rows):
            continue  # this fire already produced its review(s)
        if any(line_marker in (r.get("detail") or "")
               and r.get("state") in (None, "open") for r in rows):
            continue  # one open review per kill line
        detail = (
            f"{symbol} fired its kill line for thesis '{slug}': "
            f"trigger {fire.get('trigger_price')} vs level "
            f"{fire.get('level')} at {fire.get('fired_at')}. "
            f"Review the position for exit — the line firing is the "
            f"review trigger, not an order. "
            f"{line_marker} {fire_marker}")
        for book in books:
            # Count rows (any state) before/after: the store swallows
            # the insert when an open row already exists for the book,
            # and a state filter would miss rows whose state the DB
            # default supplies (the test fakes do not apply defaults).
            def _count() -> int:
                return len((client.table("manual_actions")
                            .select("id").eq("book", book)
                            .eq("kind", ACTION_KIND)
                            .eq("symbol", symbol)
                            .is_("idea_id", "null")
                            .execute().data) or [])
            before = _count()
            workshop_store.add_manual_action(
                client, book, None, ACTION_KIND, symbol, detail)
            if _count() > before:
                opened += 1
    return {"fires_seen": len(recent), "actions_opened": opened,
            "held_unavailable": False}


def run_bridge(client, *, now: datetime | None = None,
               positions_fn=None) -> dict:
    """One full bridge pass: sync the watches, then open the reviews
    for any recent fires. The watcher runner calls this fail-soft
    after every tick."""
    now = now or datetime.now(timezone.utc)
    sync = sync_watches(client, now=now)
    reviews = open_exit_reviews(client, now=now,
                                positions_fn=positions_fn)
    return {"sync": sync, "reviews": reviews}
