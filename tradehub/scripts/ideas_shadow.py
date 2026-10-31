"""Cron entrypoint: append each live idea's shadow-track days (Trading HQ step 3, spec §4.6).

The hub applies the idea's confirmed rules (the run that cleared the live-paper gate) to every trading day after
go-live and records what the idea would have done. Missed days are caught up in order; a day where a held ticker
has no close gets no row; today counts only after 17:00 New York, so a partial bar is never recorded.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.workshop import data, store
from tradehub.workshop.engine import daily_frame, tickers_for
from tradehub.workshop.spec import IdeaSpec

from tradehub.workshop.data import NY, last_complete_day

FRED_LEAD = timedelta(days=3 * 366)  # same FRED lead-in as the backtest route (main._fred_start)


def _rows(idea: dict, supa, cutoff: date, closes, fred, bars=None) -> list[dict]:
    # The confirmed rule runs from its own start date, exactly as in the backtest, so every lookback is warm.
    spec = IdeaSpec.model_validate(store.get_run(supa, idea["live_run_id"])["spec"])
    live_day = datetime.fromisoformat(idea["live_at"]).astimezone(NY).date()
    after = max([live_day] + [date.fromisoformat(r["day"]) for r in store.shadow_days(supa, idea["id"])])
    prices = data.with_rule_bars(spec, closes(tickers_for(spec), spec.start), spec.start, bars_fn=bars)
    series = data.rule_series(spec, spec.start - FRED_LEAD, fred=fred)
    frame = daily_frame(spec, prices, series)
    days = frame[(frame.index.date > after) & (frame.index.date <= cutoff)]
    return [{"day": str(d.date()), "ret": float(r.ret), "on": bool(r.on), "bench": float(r.bench),
             "spy": float(r.spy), "exit": str(r.exit)} for d, r in days.iterrows()]


def run(now: datetime, supa, *, closes=data.closes, fred=data.fred_series, bars=data.bars
        ) -> tuple[dict[int, int], dict[int, str]]:
    """({idea_id: rows added}, {idea_id: error}). One idea failing never stops the others."""
    cutoff = last_complete_day(now)
    added: dict[int, int] = {}
    failed: dict[int, str] = {}
    for idea in store.live_ideas(supa):
        try:
            added[idea["id"]] = len(store.append_shadow(supa, idea["id"], _rows(idea, supa, cutoff, closes, fred,
                                                                                bars)))
        except Exception as exc:  # noqa: BLE001 -- reported and retried tomorrow; the missed days catch up then
            failed[idea["id"]] = f"{type(exc).__name__}: {exc}"
    return added, failed


def main() -> int:
    load_local_env()
    try:
        added, failed = run(datetime.now(UTC), get_client())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"shadow": "failed", "error": str(exc)}))
        return 1
    print(json.dumps({"shadow": "failed" if failed else "ok", "added": added, "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
