"""FOMC statement dates (Amendment 2 to the claim-typed-gates spec, 2026-11-08).

An FOMC event is the day a meeting's statement was issued -- the meeting's last
day -- transcribed from the Federal Reserve's published meeting calendars (the
calendars page for 2021-2027, the Historical Materials year pages for
2010-2020), frozen here on 2026-11-08. This table replaces FRED release 101's
release-date list, which was the quirk: release 101 ("FOMC Press Release")
contains only the DAILY target-range series (DFEDTARU/DFEDTARL), and a FRED
release-date list holds every date any series in the release was revised --
every business day. Idea 65's "3,145 FOMC events" were ~250 weekdays a year.

Inclusions, one rule: meetings (scheduled or unscheduled) and statement-bearing
conference calls. The unscheduled entries are 2010-05-09 (swap-lines call),
2019-10-11 (statement of the Oct 4 meeting), 2020-03-03 and 2020-03-15 (the
emergency cuts). Excluded by the same rule: calls with no statement
(2010-10-15, 2011-08-01, 2011-11-28, 2013-10-16, 2014-03-04), the cancelled
2020-03-17/18 meeting, and notation-vote statements (2020-03-23, 2020-08-27,
2025-08-22) -- announcements without a meeting are a different event class.

Statements issue at 14:00 New York, so each date carries 14:00 and the event
engine's noon rule assigns the reaction day (the next trading day), as for
every afternoon release. One exception: the 2020-03-03 cut was released at
10:00 and is timestamped so. Sunday statements (2010-05-09, 2020-03-15) land
on the Monday either way.

Maintenance: extend the table from the Fed's published calendar as new years
are scheduled. A test pins the shape -- 8 dates a year, 9 in 2010, 2019 and
2020, 139 over 2010-2026 -- so a bad edit fails CI instead of silently
re-inflating the event set.
"""

from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

# (statement date, release hour New York). Hour is 14 unless noted.
_STATEMENTS: tuple[tuple[date, int], ...] = (
    # 2010 (9: the May 9 swap-lines call carried a statement)
    (date(2010, 1, 27), 14), (date(2010, 3, 16), 14), (date(2010, 4, 28), 14),
    (date(2010, 5, 9), 14), (date(2010, 6, 23), 14), (date(2010, 8, 10), 14),
    (date(2010, 9, 21), 14), (date(2010, 11, 3), 14), (date(2010, 12, 14), 14),
    # 2011
    (date(2011, 1, 26), 14), (date(2011, 3, 15), 14), (date(2011, 4, 27), 14),
    (date(2011, 6, 22), 14), (date(2011, 8, 9), 14), (date(2011, 9, 21), 14),
    (date(2011, 11, 2), 14), (date(2011, 12, 13), 14),
    # 2012
    (date(2012, 1, 25), 14), (date(2012, 3, 13), 14), (date(2012, 4, 25), 14),
    (date(2012, 6, 20), 14), (date(2012, 8, 1), 14), (date(2012, 9, 13), 14),
    (date(2012, 10, 24), 14), (date(2012, 12, 12), 14),
    # 2013
    (date(2013, 1, 30), 14), (date(2013, 3, 20), 14), (date(2013, 5, 1), 14),
    (date(2013, 6, 19), 14), (date(2013, 7, 31), 14), (date(2013, 9, 18), 14),
    (date(2013, 10, 30), 14), (date(2013, 12, 18), 14),
    # 2014
    (date(2014, 1, 29), 14), (date(2014, 3, 19), 14), (date(2014, 4, 30), 14),
    (date(2014, 6, 18), 14), (date(2014, 7, 30), 14), (date(2014, 9, 17), 14),
    (date(2014, 10, 29), 14), (date(2014, 12, 17), 14),
    # 2015
    (date(2015, 1, 28), 14), (date(2015, 3, 18), 14), (date(2015, 4, 29), 14),
    (date(2015, 6, 17), 14), (date(2015, 7, 29), 14), (date(2015, 9, 17), 14),
    (date(2015, 10, 28), 14), (date(2015, 12, 16), 14),
    # 2016
    (date(2016, 1, 27), 14), (date(2016, 3, 16), 14), (date(2016, 4, 27), 14),
    (date(2016, 6, 15), 14), (date(2016, 7, 27), 14), (date(2016, 9, 21), 14),
    (date(2016, 11, 2), 14), (date(2016, 12, 14), 14),
    # 2017
    (date(2017, 2, 1), 14), (date(2017, 3, 15), 14), (date(2017, 5, 3), 14),
    (date(2017, 6, 14), 14), (date(2017, 7, 26), 14), (date(2017, 9, 20), 14),
    (date(2017, 11, 1), 14), (date(2017, 12, 13), 14),
    # 2018
    (date(2018, 1, 31), 14), (date(2018, 3, 21), 14), (date(2018, 5, 2), 14),
    (date(2018, 6, 13), 14), (date(2018, 8, 1), 14), (date(2018, 9, 26), 14),
    (date(2018, 11, 8), 14), (date(2018, 12, 19), 14),
    # 2019 (9: the Oct 4 unscheduled meeting's statement issued Oct 11)
    (date(2019, 1, 30), 14), (date(2019, 3, 20), 14), (date(2019, 5, 1), 14),
    (date(2019, 6, 19), 14), (date(2019, 7, 31), 14), (date(2019, 9, 18), 14),
    (date(2019, 10, 11), 14), (date(2019, 10, 30), 14), (date(2019, 12, 11), 14),
    # 2020 (9: two emergency statements; the Mar 17-18 meeting was cancelled,
    # the Mar 23 notation-vote statement is excluded by the meetings rule)
    (date(2020, 1, 29), 14), (date(2020, 3, 3), 10), (date(2020, 3, 15), 14),
    (date(2020, 4, 29), 14), (date(2020, 6, 10), 14), (date(2020, 7, 29), 14),
    (date(2020, 9, 16), 14), (date(2020, 11, 5), 14), (date(2020, 12, 16), 14),
    # 2021
    (date(2021, 1, 27), 14), (date(2021, 3, 17), 14), (date(2021, 4, 28), 14),
    (date(2021, 6, 16), 14), (date(2021, 7, 28), 14), (date(2021, 9, 22), 14),
    (date(2021, 11, 3), 14), (date(2021, 12, 15), 14),
    # 2022
    (date(2022, 1, 26), 14), (date(2022, 3, 16), 14), (date(2022, 5, 4), 14),
    (date(2022, 6, 15), 14), (date(2022, 7, 27), 14), (date(2022, 9, 21), 14),
    (date(2022, 11, 2), 14), (date(2022, 12, 14), 14),
    # 2023
    (date(2023, 2, 1), 14), (date(2023, 3, 22), 14), (date(2023, 5, 3), 14),
    (date(2023, 6, 14), 14), (date(2023, 7, 26), 14), (date(2023, 9, 20), 14),
    (date(2023, 11, 1), 14), (date(2023, 12, 13), 14),
    # 2024
    (date(2024, 1, 31), 14), (date(2024, 3, 20), 14), (date(2024, 5, 1), 14),
    (date(2024, 6, 12), 14), (date(2024, 7, 31), 14), (date(2024, 9, 18), 14),
    (date(2024, 11, 7), 14), (date(2024, 12, 18), 14),
    # 2025
    (date(2025, 1, 29), 14), (date(2025, 3, 19), 14), (date(2025, 5, 7), 14),
    (date(2025, 6, 18), 14), (date(2025, 7, 30), 14), (date(2025, 9, 17), 14),
    (date(2025, 10, 29), 14), (date(2025, 12, 10), 14),
    # 2026
    (date(2026, 1, 28), 14), (date(2026, 3, 18), 14), (date(2026, 4, 29), 14),
    (date(2026, 6, 17), 14), (date(2026, 7, 29), 14), (date(2026, 9, 16), 14),
    (date(2026, 10, 28), 14), (date(2026, 12, 9), 14),
    # 2027 (as scheduled at transcription)
    (date(2027, 1, 27), 14), (date(2027, 3, 17), 14), (date(2027, 4, 28), 14),
    (date(2027, 6, 9), 14), (date(2027, 7, 28), 14), (date(2027, 9, 15), 14),
    (date(2027, 10, 27), 14), (date(2027, 12, 8), 14),
)

STATEMENT_DATES: tuple[date, ...] = tuple(d for d, _ in _STATEMENTS)


def statement_times() -> pd.DataFrame:
    """The event source for an FOMC study, in data.release_dates' shape:
    one column `time` (New York wall time, tz-naive), oldest first."""
    return pd.DataFrame({"time": [pd.Timestamp(datetime.combine(d, time(hour=h)))
                                  for d, h in _STATEMENTS]})
