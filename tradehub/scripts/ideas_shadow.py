"""Cron entrypoint: append each live idea's shadow-track days (Trading HQ step 3, spec §4.6).

The hub applies the idea's confirmed rules (the run that cleared the live-paper gate) to every trading day after
go-live and records what the idea would have done. Missed days are caught up in order; a day where a held ticker
has no close gets no row; today counts only after 17:00 New York, so a partial bar is never recorded.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.core.env import load_local_env
from tradehub.core.supabase_client import get_client
from tradehub.workshop import data, store
from tradehub.workshop.engine import daily_frame, tickers_for
from tradehub.workshop.spec import IdeaSpec

NY = ZoneInfo("America/New_York")
WARMUP = timedelta(days=3 * 366)  # lookbacks reach 756 trading days


def last_complete_day(now: datetime) -> date:
    ny = now.astimezone(NY)
    return ny.date() if ny.hour >= 17 else ny.date() - timedelta(days=1)


def run(now: datetime, supa, *, closes=data.closes, fred=data.fred_series) -> dict[int, int]:
    cutoff = last_complete_day(now)
    added: dict[int, int] = {}
    for idea in store.live_ideas(supa):
        spec = IdeaSpec.model_validate(store.get_run(supa, idea["live_run_id"])["spec"])
        live_day = datetime.fromisoformat(idea["live_at"]).astimezone(NY).date()
        have = store.shadow_days(supa, idea["id"])
        after = max([live_day] + [date.fromisoformat(r["day"]) for r in have])
        start = max(spec.start, live_day - WARMUP)
        prices = closes(tickers_for(spec), start)
        series = ({spec.when.series: fred(spec.when.series, start - WARMUP)}
                  if spec.when and spec.when.source == "fred" else {})
        frame = daily_frame(spec.model_copy(update={"start": start}), prices, series)
        days = frame[(frame.index.date > after) & (frame.index.date <= cutoff)]
        rows = [{"day": str(d.date()), "ret": float(r.ret), "on": bool(r.on), "bench": float(r.bench),
                 "spy": float(r.spy)} for d, r in days.iterrows()]
        added[idea["id"]] = len(store.append_shadow(supa, idea["id"], rows))
    return added


def main() -> int:
    load_local_env()
    try:
        out = run(datetime.now(UTC), get_client())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"shadow": "failed", "error": str(exc)}))
        return 1
    print(json.dumps({"shadow": "ok", "added": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
