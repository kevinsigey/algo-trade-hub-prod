"""Live preview of the next monthly releases (jobs, CPI): the same models, run now, never scored.

The journal freezes a forecast only inside FREEZE_LEAD of the market close, so for most of a month the
site has nothing to show for the next report. This runs the SAME forecaster classes with a wider lead
and upserts what they say into `journal_previews`. It never writes the calendar, a forecast, or a
settlement, so the scored record is untouched; a preview is replaced on every run and is labelled
"not locked" wherever it is shown.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster

log = logging.getLogger(__name__)

PREVIEWS = "journal_previews"
PREVIEW_LEAD = timedelta(days=45)


def build_previews(now: datetime, live=None, labor: LaborData | None = None) -> list[Any]:
    live = live or KalshiLive()
    forecasters = [
        CpiForecaster("KXCPI", live, fetch_market, lead=PREVIEW_LEAD),
        CpiForecaster("KXCPICORE", live, fetch_market, lead=PREVIEW_LEAD),
        PayrollsForecaster(live, fetch_market, labor or LaborData(), lead=PREVIEW_LEAD),
    ]
    rows: list[dict[str, Any]] = []
    for fc in forecasters:
        try:
            for entry in fc.targets(now):
                f = fc.forecast(entry, now)
                if f is None:
                    continue
                rows.append({
                    "target": f.target, "forecaster": f.forecaster, "forecaster_version": f.forecaster_version,
                    "family": entry.family, "close_at": entry.cutoff_at.isoformat(),
                    "probability": f.probability, "market_prob": f.market_prob, "payload": f.payload,
                    "computed_at": now.isoformat(),
                })
        except Exception:  # noqa: BLE001 - one broken source must not hide the others' previews
            log.exception("preview: %s failed", fc.name)
    return rows


def run_previews(supa, now: datetime, **kw) -> dict[str, int]:
    rows = build_previews(now, **kw)
    if rows:  # on a total failure keep the last rows: their computed_at tells the reader how old they are
        supa.table(PREVIEWS).upsert(rows, on_conflict="target,forecaster,forecaster_version").execute()
        # A strike that is no longer open (the report was released) must stop showing as a preview.
        supa.table(PREVIEWS).delete().lt("computed_at", now.isoformat()).execute()
    return {"previews": len(rows)}
