"""The print-classification store (Loop Round 4, Item 3).

`forward_file_classifications` was a provider contract before it was a
table: Spec C's band-crossing engine reads a name's forward-file state
through `band_crossing.t1_classification`, and the debate candidates'
conjunction leg (and Spec D's file_state watches, through the same reader)
reads `candidates.print_classification`. Both expect rows shaped
(`ticker`, `classification` in {improved, intact, deteriorated}, `as_of`)
and take the latest row by `as_of`. This module is the WRITE side of that
contract; the readers are unchanged.

The classifications themselves are the thesis side's print log -- their
judgments, their vocabulary. The store accepts ONLY the three consumer
values and refuses anything else loudly (a 422 at the endpoint): a value
the readers cannot see (their log's "no_surprise", a "fork-A" suffix) must
be mapped at the source -- no_surprise -> intact, fork detail -> `note` --
never stored unreadable. Append-only: a correction is a new row with a
later `as_of` (or the same date, recorded later -- readers order by as_of,
and the endpoint's read-back shows exactly what a reader would see).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

TABLE = "forward_file_classifications"
CLASSES = ("improved", "intact", "deteriorated")
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")


def _as_date(value) -> str:
    """Normalize an as_of (date, ISO date, or ISO datetime) to YYYY-MM-DD."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        raise ValueError(
            f"as_of {value!r} is not an ISO date (expected e.g. 2026-11-09)"
        ) from None


def record_classification(client, *, ticker, classification, as_of,
                          source=None, note=None, recorded_by=None,
                          now=None) -> dict:
    """Validate and append one classification row; returns the stored row.

    Raises ValueError with a named reason on any contract violation -- the
    write endpoint turns that into a 422, so a bad write is loud at the
    source instead of invisible to every reader.
    """
    symbol = str(ticker or "").strip().upper()
    if not _TICKER_RE.match(symbol):
        raise ValueError(
            f"ticker {ticker!r} is not a plain US symbol (1-12 chars, "
            "letters/digits/./-)")
    value = str(classification or "").strip().lower()
    if value not in CLASSES:
        raise ValueError(
            f"classification {classification!r} is not one of "
            f"{', '.join(CLASSES)} -- the readers accept only these three; "
            "map source vocabulary first (e.g. no_surprise -> intact, fork "
            "detail -> note)")
    day = _as_date(as_of)
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    row = {"ticker": symbol, "classification": value, "as_of": day,
           "source": (str(source).strip() or None) if source else None,
           "note": (str(note).strip() or None) if note else None,
           "recorded_by": recorded_by, "recorded_at": stamp}
    resp = client.table(TABLE).insert(row).execute()
    return (resp.data or [row])[0]
