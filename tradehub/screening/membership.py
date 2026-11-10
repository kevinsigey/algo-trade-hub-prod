"""Entrance/exit diffing for watchlist screens (Kevin, 2026-11-09 addendum).

A name ENTERING a classic screen is the signal; the static survivor list is
trivia. Screens whose spec carries `membership_diff` get their membership
diffed on every recorded run: entrances and exits become dated events on the
screen row, and the current membership (with the date each member entered)
rides beside them. Storage follows the screens table's own pattern — the
row carries its record as jsonb (last_run's precedent):

  membership         {"tracked_since": date, "as_of": date,
                      "members": {ticker: since-date}}
  membership_events  [{ticker, kind: entered|exited, date, since?}]
                     append-only, bounded to the most recent EVENT_CAP.

The FIRST diffed run baselines silently — every survivor is a member since
the baseline date and NO entrance events are written (Spec C's baseline
rule). A refresh whose survivors match the stored membership produces no
events. Display only: no alerts, no orders, no idea changes ever read this.
"""

from __future__ import annotations

EVENT_CAP = 100


def _norm(tickers) -> list[str]:
    return sorted({str(t).strip().upper() for t in tickers or [] if str(t).strip()})


def diff_membership(prior: dict | None, survivors, run_date: str) -> tuple[dict, list[dict]]:
    """(new_state, new_events) for one refresh. `prior` is the stored
    membership state (None/absent on the first diffed run -> baseline)."""
    now = _norm(survivors)
    if not prior or not isinstance(prior.get("members"), dict):
        state = {"tracked_since": run_date, "as_of": run_date,
                 "members": {t: run_date for t in now}}
        return state, []
    prior_members = {str(t).strip().upper(): str(d) for t, d in prior["members"].items()}
    events: list[dict] = []
    members: dict[str, str] = {}
    for t in now:
        if t in prior_members:
            members[t] = prior_members[t]
        else:
            members[t] = run_date
            events.append({"ticker": t, "kind": "entered", "date": run_date})
    for t in sorted(set(prior_members) - set(now)):
        events.append({"ticker": t, "kind": "exited", "date": run_date,
                       "since": prior_members[t]})
    state = {"tracked_since": prior.get("tracked_since") or run_date,
             "as_of": run_date, "members": members}
    return state, events


def append_events(existing, new_events, cap: int = EVENT_CAP) -> list[dict]:
    """The stored log is bounded by design (it is a display record on the
    screen row, in the last_run pattern): the most recent `cap` events."""
    out = [*(existing or []), *new_events]
    return out[-cap:] if cap else out


def run_date_of(last_run: dict | None) -> str:
    """The run's date (UTC) from its footer; falls back to today (UTC)."""
    run_at = ((last_run or {}).get("footer") or {}).get("run_at") or ""
    if len(run_at) >= 10:
        return run_at[:10]
    from datetime import UTC, datetime

    return datetime.now(UTC).date().isoformat()
