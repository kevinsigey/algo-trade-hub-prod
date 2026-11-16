"""The tracker grader run (Thesis v6, spec Sections 3-5; design
docs/superpowers/specs/2026-11-16-thesis-tracker-design.md, PR 4).

One run grades every due print and stamps the health row:

- For each (ticker, print) whose release has passed, the graded card
  (the latest frozen strictly before the print -- `cards.graded_card`;
  superseded cards never grade) gets its outcome from daily bars via
  `grading.grade_outcome`. An outcome is written only when every
  horizon is computable; a print whose +5 session has not happened
  yet is counted `waiting` and retried on the next run. There is no
  manual grading path: this run is the only writer of
  `forecast_outcomes`.
- Claim A/C progress is recomputed from the graded record against
  each falsifier's frozen threshold/window, and a completed verdict
  moves the falsifier out of `armed` (passed / fired / killed). A
  claim already out of `armed` is never reopened. Claim B is not
  computed here: its clusters are the 2027 hyperscaler print rounds,
  graded from the cluster record when they exist (scoreboard, PR 7).
- `tracker_health` is stamped on every run, success or failure --
  the sizing fork (spec Section 4) reads the stamp: a fresh
  successful run keeps Schedule v2 units; a stale or failed stamp
  drops the event-lab unit to $1,500 automatically.

Coverage failures (a covered print with no card) are NOT logged by
this run: the design's open question (iii) -- which earnings calendar
defines "covered" -- is still Kevin's/Claude's to settle, and this
module does not invent one. Classified prints enter the record
through their cards.

`bars_for(symbol, start_date, end_date)` is injected: the cron script
wires Alpaca daily bars; tests wire fakes. No network in this module.
"""
from __future__ import annotations

from datetime import timedelta

from tradehub.tracker import cards as cards_store
from tradehub.tracker import grading

CARDS = cards_store.TABLE
OUTCOMES = "forecast_outcomes"
FALSIFIERS = "thesis_falsifiers"
HEALTH = "tracker_health"
BENCHMARK = "SPY"
BAR_LEAD_DAYS = 14  # calendar days of bars before the print (base close)


def _instant(value):
    return cards_store._instant(value, "print_at")


def stamp_health(client, now, *, ok: bool) -> None:
    client.table(HEALTH).upsert(
        {"id": 1, "last_grader_run_at": now.isoformat(),
         "last_grader_ok": bool(ok)}, on_conflict="id").execute()


def _due_prints(client, now) -> list[tuple[str, str]]:
    resp = client.table(CARDS).select("*").execute()
    due: dict[tuple[str, str], object] = {}
    for row in resp.data or []:
        print_at = _instant(row["print_at"])
        if print_at <= now:
            due[(str(row["ticker"]).upper(), row["print_at"])] = print_at
    return sorted(due, key=lambda k: due[k])


def _graded_card_ids(client) -> set:
    resp = client.table(OUTCOMES).select("*").execute()
    return {r["card_id"] for r in resp.data or []}


def refresh_claim_states(client, fire_nets) -> dict:
    """Recompute Claim A/C progress and move any falsifier whose
    frozen window just completed out of `armed`. Returns the progress
    dicts by claim letter."""
    outcomes = client.table(OUTCOMES).select("*").execute().data or []
    card_rows = client.table(CARDS).select("*").execute().data or []
    by_id = {r["id"]: r for r in card_rows}
    graded = [o for o in outcomes if o["card_id"] in by_id]
    graded.sort(key=lambda o: (str(by_id[o["card_id"]]["print_at"]),
                               o["id"]))
    a_rows = [{"classification_hit": o.get("classification_hit")}
              for o in graded]
    falsifiers = client.table(FALSIFIERS).select("*").execute().data or []
    progress: dict = {}
    for row in falsifiers:
        claim = row.get("claim")
        if claim == "A":
            threshold = row.get("threshold") or {}
            window = row.get("window_spec") or {}
            p = grading.claim_a_progress(
                a_rows,
                prints=int(window.get("prints", 40)),
                rolling=int(window.get("rolling_kill_prints", 60)),
                min_separation=float(threshold.get("min_separation", 0.60)),
                kill_below=float(threshold.get("kill_below_rolling", 0.50)))
        elif claim == "C":
            window = row.get("window_spec") or {}
            p = grading.claim_c_progress(
                fire_nets, fires=int(window.get("fires", 5)))
        else:
            continue
        progress[claim] = p
        if row.get("state") == "armed" and p["verdict"]:
            client.table(FALSIFIERS).update({"state": p["verdict"]}) \
                .eq("id", row["id"]).execute()
    return progress


def grade_run(client, bars_for, now, *, fire_nets=()) -> dict:
    """Grade every due print once, refresh the claim states, stamp
    health. `fire_nets` is the play-kind-(a) net list in fire order,
    wired from trade_links P&L by the caller (PR 5: the grade run
    builds it from the FIFO via tracker.links.claim_c_fire_nets)."""
    already = _graded_card_ids(client)
    graded = waiting = 0
    for ticker, print_at in _due_prints(client, now):
        card = cards_store.graded_card(client, ticker, print_at)
        if card is None or card["id"] in already:
            continue
        start = (_instant(print_at) - timedelta(days=BAR_LEAD_DAYS)).date()
        end = now.date()
        outcome = grading.grade_outcome(
            card, bars_for(ticker, start, end),
            bars_for(BENCHMARK, start, end))
        if outcome is None:
            waiting += 1
            continue
        client.table(OUTCOMES).insert(
            {"card_id": card["id"], "graded_at": now.isoformat(),
             **outcome}).execute()
        already.add(card["id"])
        graded += 1
    progress = refresh_claim_states(client, fire_nets)
    stamp_health(client, now, ok=True)
    return {"graded": graded, "waiting": waiting, "claims": progress}
