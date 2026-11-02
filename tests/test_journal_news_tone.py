"""The energy news-tone journal row (phase-2 §5.1): a FIXED logistic map of the
tone z-score onto XLE's next-session direction, graded by the journal beside its
naive baselines. Unfitted by design -- what these tests pin is the sign of the
hypothesis, the gap behaviour, and the plumbing."""
from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pandas as pd
from journal_fakes import FakeJournalDB

from tradehub.journal.contract import CalendarEntry
from tradehub.journal.daily import DailyCloses
from tradehub.journal.forecasters.news_tone import EnergyToneForecaster, tone_zscore, xle_source
from tradehub.journal.nyse import is_session
from tradehub.journal.runner import run_journal

MONDAY = date(2026, 10, 19)  # an NYSE session


def _closes(n=120, seed=3, start=date(2026, 5, 1)) -> DailyCloses:
    rng, level, out, day = random.Random(seed), 90.0, {}, start
    while len(out) < n:
        if is_session(day):
            level *= 1.0 + rng.gauss(0.0004, 0.008)
            out[day] = level
        day += timedelta(days=1)
    last = max(out)
    source = xle_source(chart=lambda ticker, s: (out, "America/New_York"))
    closes = DailyCloses(source)
    closes._closes, closes._hour = out, None
    return closes, last


def _tone(newest: float, base: float = 0.0, days: int = 70, end: date = date(2026, 10, 16)):
    stamps = pd.bdate_range(end=end, periods=days)
    values = [base + (0.6 if i % 2 else -0.6) for i in range(days - 1)] + [newest]
    return pd.Series(values, index=stamps, name="tone")


def _forecaster(tone: pd.Series) -> EnergyToneForecaster:
    closes, _ = _closes()
    return EnergyToneForecaster(closes, tone_fn=lambda basket, start: tone)


def _entry(day: date = MONDAY) -> CalendarEntry:
    return CalendarEntry(f"xle:{day.isoformat()}:up", "xle", "daily",
                         datetime(2026, 10, 19, 13, 0, tzinfo=UTC), climatology_prob=0.5)


def test_deeply_negative_tone_leans_up_and_euphoria_leans_down():
    down = _forecaster(_tone(-6.0)).forecast(_entry(), datetime(2026, 10, 19, 12, 0, tzinfo=UTC))
    up = _forecaster(_tone(6.0)).forecast(_entry(), datetime(2026, 10, 19, 12, 0, tzinfo=UTC))
    assert down is not None and down.probability > 0.75 and down.payload["z"] < -3
    assert up is not None and up.probability < 0.25 and up.payload["z"] > 3
    assert down.payload["tone_day"] == "2026-10-16" and down.payload["basket"] == "ENERGY"


def test_neutral_tone_is_a_coin_flip():
    fc = _forecaster(_tone(0.1)).forecast(_entry(), datetime(2026, 10, 19, 12, 0, tzinfo=UTC))
    assert fc is not None and abs(fc.probability - 0.5) < 0.1


def test_short_history_stale_tone_and_a_gdelt_failure_are_gaps_not_guesses():
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    assert _forecaster(_tone(-6.0, days=10)).forecast(_entry(), now) is None  # < MIN_WINDOW behind
    stale = _tone(-6.0, end=date(2026, 10, 8))  # newest tone 11 days before the session
    assert _forecaster(stale).forecast(_entry(), now) is None

    def down(basket, start):
        raise RuntimeError("GDELT refused")

    closes, _ = _closes()
    assert EnergyToneForecaster(closes, tone_fn=down).forecast(_entry(), now) is None


def test_tone_zscore_uses_only_days_before_the_session():
    tone = _tone(-6.0)
    tone.loc[pd.Timestamp(MONDAY)] = 99.0  # the session day's own tone must not leak in
    found = tone_zscore(tone, MONDAY)
    assert found is not None and found[1] == date(2026, 10, 16) and found[2] == -6.0


def test_the_row_freezes_and_settles_through_the_runner():
    closes, last = _closes()
    tone = _tone(-6.0, end=last - timedelta(days=1))
    fc = EnergyToneForecaster(closes, tone_fn=lambda basket, start: tone)
    db = FakeJournalDB(lambda: now)
    # sit just before a freeze whose target the fake closes can settle later
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    out = run_journal(db, [fc], now)
    assert out["failures"] == []


def test_sector_rows_run_the_same_fixed_map_on_their_own_basket_and_etf():
    """The 2026-11-01 generalization: every SPDR sector gets the energy rule
    verbatim -- its own basket in the payload, its own ETF's target key."""
    from tradehub.journal.forecasters.news_tone import SECTORS, SectorToneForecaster, etf_source

    tone = _tone(newest=3.0)
    closes, _ = _closes()
    fc = SectorToneForecaster("financials", "FINANCIALS", closes, tone_fn=lambda basket, start: tone)
    assert (fc.name, fc.version) == ("financials_news_tone", "tone-z-v1")
    energy = _forecaster(tone).forecast(_entry(), datetime(2026, 10, 19, 13, 0, tzinfo=UTC))
    mine = fc.forecast(_entry(), datetime(2026, 10, 19, 13, 0, tzinfo=UTC))
    assert mine.probability == energy.probability  # the identical fixed map
    assert mine.payload["basket"] == "FINANCIALS" and energy.payload["basket"] == "ENERGY"
    assert etf_source("XLF").family == "xlf" and len(SECTORS) == 11
