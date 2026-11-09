"""The FOMC statement table (spec 2026-11-08, Amendment 2): true meeting
statement dates from the Fed's published calendars, replacing FRED release
101's release-date list -- which, release 101 holding only the DAILY
target-range series, was every business day (~250/year, the 3,145-"event"
quirk in idea 65). These tests pin the table's shape so a bad edit fails CI
instead of silently re-inflating the event set."""

from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from tradehub.workshop.events import EventSpec, run_event_test
from tradehub.workshop.fomc_calendar import STATEMENT_DATES, statement_times


def test_the_table_has_meeting_frequency_not_daily_frequency():
    years = Counter(d.year for d in STATEMENT_DATES if d.year <= 2026)
    assert set(years) == set(range(2010, 2027))
    for y, n in years.items():
        assert n == (9 if y in (2010, 2019, 2020) else 8), (y, n)
    assert sum(years.values()) == 139  # true meetings, not 3,145 weekdays


def test_spot_dates_inclusions_and_exclusions():
    s = set(STATEMENT_DATES)
    assert date(2026, 12, 9) in s  # the December 2026 meeting (statement day = last day)
    assert date(2020, 3, 3) in s and date(2020, 3, 15) in s  # the emergency cuts were meetings
    assert date(2010, 5, 9) in s  # the swap-lines call carried a statement
    assert date(2019, 10, 11) in s  # the Oct 4 meeting's statement issued Oct 11
    assert date(2020, 3, 23) not in s  # a notation-vote statement: no meeting, a different class
    assert date(2020, 3, 18) not in s  # the cancelled March 2020 meeting never issued one
    assert date(2014, 3, 4) not in s  # an unscheduled call with no statement
    assert list(STATEMENT_DATES) == sorted(set(STATEMENT_DATES))  # ordered, unique


def test_statement_times_shape_and_release_hours():
    f = statement_times()
    assert list(f.columns) == ["time"] and f["time"].is_monotonic_increasing
    assert set(f["time"].dt.hour) <= {10, 14}
    mar3 = f[f["time"].dt.date == date(2020, 3, 3)].iloc[0]["time"]
    assert mar3.hour == 10  # the emergency cut was released at 10:00, before the noon rule
    assert len(f) == len(STATEMENT_DATES)


def test_an_fomc_study_counts_meetings_not_weekdays():
    idx = pd.bdate_range("2017-12-01", "2022-01-31")
    rng = np.random.default_rng(3)
    spy = rng.normal(0.0003, 0.01, len(idx))
    closes = pd.DataFrame({"SPY": 100 * np.cumprod(1 + spy)}, index=idx)
    spec = EventSpec.model_validate({
        "title": "Post-FOMC drift (SPY, all FOMCs)", "tickers": ["SPY"], "event": "fomc",
        "window": "drift_1_5", "direction": "up", "benchmark": "SPY", "start": "2018-01-02"})
    out = run_event_test(spec, closes, {"*": statement_times()}, variations=1, seed=7)
    # Statements 2018-2021: 8 + 9 + 9 + 8 = 34. The release-101 source would
    # have found ~1,000 weekdays over the same span.
    assert out["n_events"] == 34, out["n_events"]
