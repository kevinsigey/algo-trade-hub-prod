"""Code cadences vs the database's cadence check: one set, three homes.

`journal_calendars` carries a CHECK constraint on cadence, widened by hand
each time the code learns a new one. Twice that widening was missed -- the
hourly family in 2026-11 (migration 20261102000001 tells that story) and
'15min' in PR #370 -- and both times the failure was silent: the runner
records a per-forecaster failure and the family freezes nothing. This test
reconstructs the constraint the migrations leave standing and pins it to
`contract.CADENCES`, so the next new cadence fails HERE instead of in prod.
"""
import re
from pathlib import Path

from tradehub.journal.contract import CADENCES
from tradehub.journal.scoring import MIN_SETTLED

MIGRATIONS = Path(__file__).resolve().parents[1] / "market_sentiment_tool" / "supabase" / "migrations"


def _db_cadences() -> set[str]:
    """The cadence set the journal_calendars check enforces after every
    migration runs: the create-table IN list, replaced by each later
    add-constraint array in filename order."""
    standing: set[str] = set()
    for path in sorted(MIGRATIONS.glob("*.sql")):
        text = path.read_text()
        created = re.search(r"cadence\s+text NOT NULL CHECK \(cadence IN \(([^)]*)\)\)", text)
        if created:
            standing = set(re.findall(r"'([^']+)'", created.group(1)))
        for array in re.findall(r"journal_calendars_cadence_check\s+check \(cadence = any \(array\[([^\]]*)\]\)\)", text):
            standing = set(re.findall(r"'([^']+)'", array))
    return standing


def test_the_database_cadence_check_matches_the_code():
    assert _db_cadences() == set(CADENCES)


def test_every_cadence_has_a_settled_minimum():
    assert set(MIN_SETTLED) == set(CADENCES)
