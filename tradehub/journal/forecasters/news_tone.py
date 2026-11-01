"""Energy news tone forecaster (phase-2 §5.1): the journal row that grades the
Workshop's news signal itself.

Target: `xle:<session>:up` -- XLE's next NYSE session direction, the same daily
plumbing as wave 2. The forecast is the tone signal and nothing else:

    z = (latest completed day's ENERGY tone - its trailing-60-day mean) / std
    p(up) = sigmoid(-SLOPE * z)

The sign is the hypothesis under test -- "is news tone already in the price?": a
deeply negative tone surprise says the bad news is out and over-discounted, so the
next session leans up; euphoria leans down. The mapping is FIXED (SLOPE chosen once,
no fitted parameters, nothing refit as rows settle): the scorecard grades whether
this exact rule carries any skill against climatology and the naive baselines that
sit beside it. If it doesn't, the row lives at "measured, no edge" -- which is the
answer the Workshop condition (§5.1 first half) also feeds on.

Data honesty, inherited from workshop/news.py: GDELT's free API covers ~3 months
and throttles hard, so early rows are few and a tone outage is a recorded GAP
(forecast returns None), never a stale or invented probability.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pandas as pd

from tradehub.data.yahoo_chart import fetch_chart
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.daily import DailyCloses, DailySource, daily_entry, settle_daily, target_day
from tradehub.journal.nyse import is_session
from tradehub.workshop.news import news_tone_series

BASKET = "ENERGY"
WINDOW_DAYS = 60        # the trailing window the z-score reads against
MIN_WINDOW = 20         # fewer tone days than this and there is nothing to grade against
STALE_DAYS = 4          # newest tone day older than this before the session -> a gap, not a guess
SLOPE = 0.75            # the fixed logistic slope of the tone map; unfitted by design


def xle_source(chart=fetch_chart) -> DailySource:
    return DailySource("xle", "yahoo:XLE", lambda start: chart("XLE", start), is_session)


def tone_zscore(tone: pd.Series, day: date) -> tuple[float, date, float] | None:
    """(z, newest_day, newest_tone) from tone days strictly before `day`, or None.

    The window is the WINDOW_DAYS before the newest day; the newest day is the one
    being scored against it. Mirrors the Workshop's zscore read so the journal row
    and a Workshop run of the same rule see the same number.
    """
    past = tone[tone.index < pd.Timestamp(day)].dropna().sort_index()
    if past.empty:
        return None
    newest_day, newest = past.index[-1], float(past.iloc[-1])
    if (day - newest_day.date()) > timedelta(days=STALE_DAYS):
        return None
    window = past.iloc[:-1].tail(WINDOW_DAYS)
    if len(window) < MIN_WINDOW:
        return None
    mean, std = float(window.mean()), float(window.std(ddof=1))
    if not std > 0:
        return None
    return (newest - mean) / std, newest_day.date(), newest


class EnergyToneForecaster:
    cadence = "daily"
    name = "energy_news_tone"
    version = "tone-z-v1"

    def __init__(self, closes: DailyCloses, tone_fn=news_tone_series):
        self._closes, self._tone_fn = closes, tone_fn

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return daily_entry(now, self._closes)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        try:
            tone = self._tone_fn(BASKET, day - timedelta(days=WINDOW_DAYS + 40))
        except Exception:
            return None  # GDELT down/throttled with no cache: a gap, never a guess
        found = tone_zscore(tone, day)
        if found is None:
            return None
        z, tone_day, tone_value = found
        clamped = max(-10.0, min(10.0, z))  # a near-zero window std must not blow the map up
        prob = 1.0 / (1.0 + math.exp(SLOPE * clamped))  # sigmoid(-SLOPE * z)
        return Forecast(self.name, self.version, entry.target, prob,
                        payload={"basket": BASKET, "tone_day": tone_day.isoformat(),
                                 "tone": tone_value, "z": z, "slope": SLOPE,
                                 "window_days": WINDOW_DAYS, "source": "gdelt:timelinetone"})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_daily(target, now, self._closes)
