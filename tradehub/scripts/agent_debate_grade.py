"""Cron entrypoint: agent-debate grading (feed spec §7) — score every due
run at +5d/+20d against its ticker's closes and print the record.

A6 (2026-11-11): until now `grader.grade_all` had exactly one caller, the
manual operator CLI (`agent_debate grade`). No cron, route, or hook ever
invoked it, so the +5-day grades due Nov 9 simply never ran — production
had run artifacts and no grades.json at all. This entrypoint is the
scheduled caller; the CLI stays for manual re-runs. Suggested cadence:
nightly, beside the other nightly grades (deploy-side act). Grading only:
no orders, no path to them, and the debates page is untouched."""

from __future__ import annotations

import json
import sys
from datetime import datetime

from tradehub.agents import grader, store
from tradehub.workshop import data


def _closes_fn(ticker: str):
    frame = data.closes([ticker], datetime(2000, 1, 1).date())
    return frame[ticker]


def grade(closes_fn=None) -> dict:
    """One grading pass: every due run/horizon, then the record summary.
    Idempotent — already-graded (run, horizon) pairs are skipped by
    grade_all, so a re-run grades nothing new."""
    done = grader.grade_all(closes_fn=closes_fn or _closes_fn)
    return {"graded": [g.model_dump() for g in done],
            "record": grader.record_summary(store.load_grades())}


def main() -> int:
    print(json.dumps(grade(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
