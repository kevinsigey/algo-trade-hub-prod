#!/usr/bin/env python3
"""Walk-forward replay of picker v1 vs v2 over the journal's frozen
wti-hourly-v4-hl-shadow ladders (the appendix measurement for the spec
docs/superpowers/specs/2026-11-09-hourly-best-strike-picker-v2-amendment.md).

Usage: oil_picker_v2_replay.py <dump.json>, where the dump is one row
per quoted+settled journal forecast:
    SELECT f.target, f.probability, (f.payload->>'yes_bid')::float AS bid,
           (f.payload->>'yes_ask')::float AS ask, s.outcome
    FROM journal_forecasts f JOIN journal_settlements s ON s.target = f.target
    WHERE f.forecaster='oil_wti_hourly'
      AND f.forecaster_version='wti-hourly-v4-hl-shadow'
      AND f.payload->>'yes_bid' IS NOT NULL AND f.payload->>'yes_ask' IS NOT NULL;

Each event is replayed with a calibration map fitted ONLY on earlier
events (the walk-forward rule the live picker runs under). Four rules
are graded per event: v1 (raw, gross >= 5), v2 (calibrated, gross >=
15), and two reference variants that separate the bar from the map
(raw, gross >= 15; calibrated, net >= 15).

Caveat, carried from the existing backtest: the journal froze these
ladders at its own ~65-minute lead, not at T-30, so absolute levels are
the journal-lead numbers; the comparison across rules is the read.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tradehub.engines.oil_hourly import event_hour  # noqa: E402
from tradehub.oil_calibration import CalSample, apply_map, fit_map  # noqa: E402
from tradehub.oil_live import TAKER_FEE_RATE, pick_best_strike, pick_best_strike_v2  # noqa: E402


def _event_of(target: str) -> str:
    parts = target.split("-")
    return f"{parts[0]}-{parts[1]}"


def _grade(pick: dict, outcomes: dict[float, int]) -> float:
    hit = (outcomes[pick["strike"]] == 1) == (pick["side"] == "yes")
    cost = pick["cost"]
    return (1.0 if hit else 0.0) - cost - TAKER_FEE_RATE * cost * (1 - cost)


def main() -> None:
    rows = json.loads(Path(sys.argv[1]).read_text())
    by_event: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_event[_event_of(r["target"])].append(r)
    events = sorted(by_event, key=event_hour)
    samples: list[CalSample] = []
    rules = {"v1_raw_gross>=5": [], "v2_cal_gross>=15": [],
             "ref_raw_gross>=15": [], "ref_cal_net>=15": []}
    map_kinds: dict[str, int] = defaultdict(int)
    for event in events:
        close = event_hour(event)
        ladder, outcomes = [], {}
        for r in by_event[event]:
            strike = float(r["target"].split("-")[2][1:])
            ladder.append({"strike": strike, "ours": float(r["probability"]),
                           "market": (float(r["bid"]) + float(r["ask"])) / 2,
                           "yes_bid": float(r["bid"]), "yes_ask": float(r["ask"])})
            outcomes[strike] = int(r["outcome"])
        cmap = fit_map(samples)
        map_kinds[cmap.kind] += 1
        picks = {}
        picks["v1_raw_gross>=5"] = pick_best_strike(ladder)[0]
        picks["v2_cal_gross>=15"] = pick_best_strike_v2(ladder, lambda p: apply_map(cmap, p))[0]
        picks["ref_raw_gross>=15"] = pick_best_strike_v2(ladder, lambda p: p)[0]
        _pick, closest = pick_best_strike_v2(ladder, lambda p: apply_map(cmap, p))
        picks["ref_cal_net>=15"] = closest if closest and closest["net_pts"] >= 15.0 else None
        for name, pick in picks.items():
            if pick is not None:
                rules[name].append(_grade(pick, outcomes))
        samples.extend(CalSample(float(r["probability"]), int(r["outcome"]) == 1, close)
                       for r in by_event[event])
    span_days = (event_hour(events[-1]) - event_hour(events[0])).total_seconds() / 86400
    print(f"events replayed: {len(events)} over {span_days:.2f} days "
          f"(journal lead, not T-30) | map kinds per event: {dict(map_kinds)}")
    print(f"{'rule':<20} {'picks':>6} {'picks/day':>10} {'net/contract':>13}")
    for name, evs in rules.items():
        net = sum(evs) / len(evs) if evs else float("nan")
        print(f"{name:<20} {len(evs):>6} {len(evs) / span_days:>10.2f} {net:>13.4f}")


if __name__ == "__main__":
    main()
