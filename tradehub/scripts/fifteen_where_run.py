"""Step A runner: build the fifteen_where report and write it where the
API serves it ($TRADEHUB_RESEARCH_DIR/fifteen_where.json).

    python -m tradehub.scripts.fifteen_where_run
    python -m tradehub.scripts.fifteen_where_run --forward-json rows.json \
        --replay part1.jsonl part2.jsonl

Forward rows come from `fifteen_window_offsets` in the database (the
--forward-json form exists for offline checks against an export). The
forward `fillable` flag is attached from the minute tape with the
candidates scorer's own bucketing: the ask size on the trade's side at
the entry minute must cover the demo's 1% size at that cost. Windows
without tick coverage keep fillable=None -- excluded from the fillable
view, never guessed.

Replay rows come from the accumulating A0 archive
(fifteen_replay_offsets.jsonl in the research dir). Their pnl already
carries the 1c haircut; nothing here re-applies it.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from tradehub.research.fifteen_where import build_report


def load_jsonl(paths: list[Path]) -> list[dict]:
    rows = []
    for path in paths:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def attach_forward_fillable(client, rows: list[dict]) -> None:
    """In place: fillable on traded forward rows from the tick tape."""
    from tradehub.fifteen_candidates import demo_size
    from tradehub.fifteen_tracking import _tick_buckets, fetch_ticks

    closes: dict[str, set[str]] = {}
    for r in rows:
        closes.setdefault(r["series"], set()).add(str(r["close_time"]))
    sizes: dict[tuple[str, str, int], dict] = {}
    for series, close_times in sorted(closes.items()):
        by_close: dict[str, list[dict]] = {}
        for tick in fetch_ticks(client, series, sorted(close_times)):
            by_close.setdefault(str(tick["close_time"]), []).append(tick)
        for close_time, ticks in by_close.items():
            for k, tick in _tick_buckets(ticks).items():
                sizes[(series, close_time, k)] = {
                    "yes": tick.get("yes_ask_size"), "no": tick.get("no_ask_size")}
    for r in rows:
        if r.get("side") is None or r.get("side_cost") is None:
            continue
        book = sizes.get((r["series"], str(r["close_time"]), int(r["offset_min"])))
        if not book:
            continue
        size = book.get(r["side"])
        if size is not None:
            r["fillable"] = float(size) >= demo_size(float(r["side_cost"]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forward-json", help="exported fifteen_window_offsets JSON (offline)")
    ap.add_argument("--replay", nargs="*", help="replay JSONL paths (default: research archive)")
    ap.add_argument("--out", help="output path (default: $TRADEHUB_RESEARCH_DIR/fifteen_where.json)")
    args = ap.parse_args(argv)

    research = Path(os.environ.get("TRADEHUB_RESEARCH_DIR", "/cache/research"))
    if args.forward_json:
        forward = json.loads(Path(args.forward_json).read_text())
    else:
        from tradehub.core.supabase_client import get_client
        from tradehub.journal import store
        from tradehub.oil_fifteen_rule import OFFSETS_TABLE

        client = get_client()
        forward = store.select_all(client, OFFSETS_TABLE, lambda q: q,
                                     ("close_time", "series", "target", "offset_min"))
        attach_forward_fillable(client, forward)

    replay_paths = [Path(p) for p in args.replay] if args.replay else \
        [research / "fifteen_replay_offsets.jsonl"]
    replay = load_jsonl(replay_paths)

    report = build_report(forward, replay)
    report["generated_at"] = datetime.now(UTC).isoformat()
    out = Path(args.out) if args.out else research / "fifteen_where.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report))
    print({"forward_rows": len(forward), "replay_rows": len(replay), "out": str(out)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
