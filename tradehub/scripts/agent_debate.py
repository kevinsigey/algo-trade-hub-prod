"""Operator CLI for the agent debate feed (feed spec §3).

  run <TICKER> [--date YYYY-MM-DD]   one debate, stored either way (needs the framework env)
  import <raw.json>                  import a framework output JSON produced elsewhere
  grade                              score every due run at +5d/+20d and print the record
  list                               print the feed payload (cards + record)

The framework env (isolated, never the hub's): python -m venv tradehub/agents/.venv and
pip install -r tradehub/agents/requirements.txt into it, or set TRADEHUB_AGENTS_PYTHON.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path


from tradehub.agents import grader, importer, payload, runner, store  # noqa: E402
from tradehub.workshop import data  # noqa: E402


def _latest_session() -> str:
    from tradehub.workshop.data import last_complete_day
    return last_complete_day(datetime.now(UTC)).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("ticker")
    p_run.add_argument("--date", default=None)
    p_imp = sub.add_parser("import")
    p_imp.add_argument("file")
    p_imp.add_argument("--date", default=None)
    sub.add_parser("grade")
    sub.add_parser("list")
    args = parser.parse_args()

    if args.cmd == "run":
        record = runner.run_debate(args.ticker, args.date, latest_session=_latest_session())
        print(record.model_dump_json(indent=1))
        return 0 if record.status in ("complete", "partial") else 1
    if args.cmd == "import":
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        now = datetime.now(UTC)
        from tradehub.agents.runner import _stamps
        run_at_ct, run_at_utc, slug = _stamps(now)
        as_of = args.date or _latest_session()
        record = importer.build_record(raw, run_id=f"{str(raw.get('ticker', 'run')).lower()}-{slug}",
                                       run_at_ct=run_at_ct, run_at_utc=run_at_utc, as_of_date=as_of,
                                       historical=as_of < _latest_session())
        store.save_run(record, importer.build_report(raw))
        print(record.model_dump_json(indent=1))
        return 0
    if args.cmd == "grade":
        def closes_fn(ticker: str):
            frame = data.closes([ticker], datetime(2000, 1, 1).date())
            return frame[ticker]
        done = grader.grade_all(closes_fn=closes_fn)
        print(json.dumps({"graded": [g.model_dump() for g in done],
                          "record": grader.record_summary(store.load_grades())}, indent=1))
        return 0
    runs, grades = store.list_runs(), store.load_grades()
    print(json.dumps(payload.feed(runs, grades, latest_session=_latest_session()), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
