"""Shared API helpers — the error taxonomy and snapshot reads every
router uses. Split from tradehub/api/main.py in step 20 (code health);
main.py re-exports these names, so existing imports keep working.
"""

# The slow read-only pages (health, macro, weather, weather map) are built
# hourly by the journal job into snapshots (tradehub/precompute.py) and
# served from them while fresh; the live build remains the fallback for a
# missing or stale snapshot, so a stopped job degrades to the old
# behaviour, never to an error. 90 minutes covers one missed hourly run.
SNAPSHOT_MAX_AGE_SECONDS = 5400


import functools
import logging
import threading
import time

from fastapi import Depends, HTTPException

from tradehub import snapshots as _snapshots
from tradehub.api.dependencies import get_supabase
from tradehub.scripts.shadow_performance import MissingCredentialError


# Table -> the migration that creates it. A table that is missing is almost always a migration that
# was never applied, so the response says which one instead of forwarding PostgREST's PGRST205 dump.
# Found the hard way on 2026-09-27: /shadow, /api/positions and /api/pnl_summary were all red in
# production with an error no reader could act on.
log = logging.getLogger(__name__)

TABLE_MIGRATIONS = {
    "gap_snapshots": "20261103000009_gap_tracker.sql",
    "signal_events": "20260415090000_signal_events_unification.sql",
    "crypto_signal_events": "20260415090000_signal_events_unification.sql",
    "predictions": "20260416000003_predictions_ledger.sql",
    "paper_trades": "20260416000011_war_room_tables.sql",
    "live_opportunities": "20260416000011_war_room_tables.sql",
    "paper_signals": "20260416000011_war_room_tables.sql",
    "trade_history": "20260416000011_war_room_tables.sql",
    "scanner_runs": "20260416000011_war_room_tables.sql",
    "backtest_runs": "20260416000004_backtest_runs.sql",
    "kalshi_quarantine_edges": "20260428000012_kalshi_quarantine_edges.sql",
}


# How postgREST says "that table is not there". Matched on the text, never on the exception type:
# postgrest raises its own APIError, which is not a RuntimeError, so a handler that caught
# RuntimeError to find this never ran and the raw PGRST205 dump went out with a 500 instead.
_MISSING_TABLE_MARKERS = ("PGRST205", "schema cache", "Could not find the table")


def _is_missing_table(exc: Exception) -> bool:
    """True when the database does not have the table, whatever exception type carries the news."""
    detail = str(exc)
    return any(marker in detail for marker in _MISSING_TABLE_MARKERS)


# ── The three answers a failed read can have, by status and by name ────────────
# A client branches on the status; a human or a log greps the name. Both are needed, because the
# two deployment-step statuses (503 and 424) are close enough that a client that only remembers one
# of them reintroduces exactly the confusion this replaces.
_STATUS_MISSING_TABLE = 503
_STATUS_MISSING_CREDENTIALS = 424
_STATUS_INTERNAL_ERROR = 500

_CODE_MISSING_TABLE = "missing_table"
_CODE_MISSING_CREDENTIALS = "missing_credentials"
_CODE_INTERNAL_ERROR = "internal_error"

# Env var name -> what it is for. The named service in the message, the variables to set, and the
# file to set them in, all come from here, so adding a credentialed service is a one-line change
# rather than a rewrite of a sentence that has to stay in step with compose.yml.
CREDENTIAL_SOURCES: dict[str, tuple[str, ...]] = {
    "alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "supabase": ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"),
}

# Text fallback for a missing credential raised by something other than
# `tradehub.scripts.shadow_performance.MissingCredentialError` -- `market_sentiment_tool`'s
# orchestrator raises its own for the same two variables, and a helper that only understood one
# module's class would go back to guessing the moment a second caller appeared. Same reason and same
# trade-off as `_is_missing_table`: match the news wherever it is carried, and prefer the typed
# check, which is why `_is_missing_credential` tries the class first.
_CREDENTIAL_MARKERS = ("alpaca api credential", "alpaca_api_key", "supabase credential", "supabase_url")


def _is_missing_credential(exc: Exception) -> bool:
    """True when the read failed because a credential was not set.

    The typed check comes first because it is exact. The text check is the backstop, for a raise
    that did not come from here.
    """
    if isinstance(exc, MissingCredentialError):
        return True
    lowered = str(exc).lower()
    return any(marker in lowered for marker in _CREDENTIAL_MARKERS)


def _credential_variables(exc: Exception) -> tuple[str, ...]:
    """The exact variables to set, preferring what the exception says it was looking for.

    `MissingCredentialError` carries them, so the message is generated from the check that failed
    rather than from a guess at which service was involved. Anything else falls back to the table
    above, keyed off the same text that identified it.
    """
    if isinstance(exc, MissingCredentialError) and exc.variables:
        return exc.variables
    lowered = str(exc).lower()
    for service, variables in CREDENTIAL_SOURCES.items():
        if service in lowered:
            return variables
    return tuple(var for variables in CREDENTIAL_SOURCES.values() for var in variables)


def _credential_service(exc: Exception) -> str:
    """What the credentials are for, in words, for the message to open with.

    Prefers the label the exception carries. A raise that did not come from
    `MissingCredentialError` is keyed off the same text that identified it, so the sentence names a
    service rather than saying "upstream service" and leaving the reader to infer it.
    """
    carried = getattr(exc, "service", "")
    if carried:
        return str(carried)
    lowered = str(exc).lower()
    for service in CREDENTIAL_SOURCES:
        if service in lowered:
            return f"{service.title()} API"
    return "upstream API"


def _missing_credential_message(exc: Exception) -> str:
    """An actionable sentence for a failure a human fixes by setting environment variables.

    It has to name the variables and where they go, because "Missing Alpaca API credentials" is not
    an instruction: it is the name of the problem, and the operator still has to work out which
    file on which machine. `vps-stack/compose.yml` passes no `ALPACA_*` to the tradehub service at
    all, so setting the variables alone would not be enough -- the service block has to name them
    too, exactly as it already does for `FRED_API_KEY`.

    Deliberately contains no `supabase/migrations/` path. The frontend classifies a failed read as
    "waiting on a database migration" by matching that substring
    (`market_sentiment_tool/src/lib/shadowPerformance.ts`), and an unset credential is not a
    migration. Naming one here would be the third way for this endpoint to say something false.
    """
    variables = _credential_variables(exc)
    service = _credential_service(exc)
    names = " and ".join(variables)
    compose_lines = " and ".join(f"'{name}: ${{{name}:-}}'" for name in variables)
    alias = (
        " SUPABASE_URL is also accepted as VITE_SUPABASE_URL."
        if "SUPABASE_URL" in variables
        else ""
    )
    return (
        f"This service has no {service} credentials, so the shadow timeline cannot be read. "
        f"The database is fine -- this is not a migration. "
        f"Set {names} in the stack's .env file, beside vps-stack/compose.yml.{alias} "
        f"Then add {compose_lines} to the tradehub service's environment: block, and redeploy."
    )


def _missing_table_message(table: str, exc: Exception) -> str:
    """An actionable sentence for a failure a human has to fix by applying a migration."""
    migration = TABLE_MIGRATIONS.get(table)
    detail = str(exc)
    if _is_missing_table(exc):
        if migration:
            extra = ""
            if table == "signal_events":
                # The rename has not been applied, so the live project still has the old name.
                extra = " The database still has crypto_signal_events under its old name."
            return (f"table '{table}' is not in the database. Apply "
                    f"market_sentiment_tool/supabase/migrations/{migration} and redeploy.{extra}")
        return f"table '{table}' is not in the database and no migration in this repo creates it."
    return detail


def _table_fault(table: str, exc: Exception) -> HTTPException:
    """The one place a failed read becomes an HTTP answer, for every handler that has one.

    THREE different facts, and a reader has to be able to tell them apart without reading prose:

    - the table is not in the database. A fact about the deployment, fixed by applying a
      migration. 503, `missing_table`, and the detail names the file.
    - the table is fine and a CREDENTIAL is missing. Also a fact about the deployment, fixed by
      setting environment variables -- and a completely different act. 424, `missing_credentials`,
      and the detail names the variables and the file to put them in.
    - anything else. A fact about this code. 500, `internal_error`, and the exception text.

    Three statuses, not three sentences, because the status is the one field a client can branch on
    without parsing English. Two of these are still "a human has to go and do something", and giving
    them one status is what made this undiagnosable: /api/shadow-performance served a bare
    "Missing Alpaca API credentials" string under a 500, and a reader could not tell from that
    whether the migration was still unapplied, the credentials were still unset, or the code was
    broken. All three said the same thing, and all three needed a different next step.

    424 Failed Dependency is the deliberate choice for the credential case rather than a second 503:
    it is unused anywhere in this repo, it is a real RFC 4918 code, and "this request failed because
    a dependency it needs did not succeed" is exactly the situation -- the Alpaca market-data API is
    a dependency of this endpoint, and this deployment cannot reach it. A reader who has never seen
    424 before does not need to have: the `code` below is the name, and the status is the fallback
    for a client that only looks at numbers.

    `detail` stays a plain string on all three, because the frontend reads `payload.detail` and
    hands it straight to a person (`market_sentiment_tool/src/hooks/useShadowPerformance.ts`). This
    is why classification cannot live in the body alone; the body is prose, and prose is what this
    endpoint has been reduced to.
    """
    if _is_missing_credential(exc):
        return HTTPException(
            status_code=_STATUS_MISSING_CREDENTIALS,
            detail=_missing_credential_message(exc),
            headers={"X-Error-Code": _CODE_MISSING_CREDENTIALS},
        )
    if _is_missing_table(exc):
        return HTTPException(
            status_code=_STATUS_MISSING_TABLE,
            detail=_missing_table_message(table, exc),
            headers={"X-Error-Code": _CODE_MISSING_TABLE},
        )
    return HTTPException(
        status_code=_STATUS_INTERNAL_ERROR,
        detail=str(exc),
        headers={"X-Error-Code": _CODE_INTERNAL_ERROR},
    )


def _snapshot(name: str) -> dict | None:
    return _snapshots.read_snapshot(name, max_age_seconds=SNAPSHOT_MAX_AGE_SECONDS)

# PostgREST caps a single response at 1000 rows whatever `limit` says, so any read that must
# see more has to page with .range() explicitly.
POSTGREST_CAP = 1000



def _fetch_all(supa, table: str, build, *, page: int = POSTGREST_CAP, cap: int | None = None,
               order: tuple[str, ...] = ("id",)) -> list[dict]:
    """Read a whole table through ordered `.range()` pages.

    A single `.execute()` returns at most PostgREST's 1000-row cap regardless of the `limit`
    asked for, so any read that must see more has to page explicitly and stop on a short page.

    The `.order()` is not decoration. PostgREST without ORDER BY returns rows in whatever order
    the query plan produces, and that order is not guaranteed to be the same between two
    requests, so `.range(0,999)` followed by `.range(1000,1999)` can repeat a row and skip
    another. On this endpoint that means a `total` that does not match the sum of the pages, and
    a keep/drop scorecard computed from a set with duplicates. `id` is the only column that is
    unique and immutable on all three tables read here, so it is the only safe ordering.
    """
    rows: list[dict] = []
    lo = 0
    while True:
        # PostgREST `Range` is inclusive of the last index, so page boundaries advance by `page`.
        # Chain .order() calls for each column (postgrest-py >=2.x only accepts one column per call).
        query = build(supa.table(table))
        for col in order:
            query = query.order(col)
        chunk = query.range(lo, lo + page - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows[:cap] if cap is not None else rows
        lo += page
        if cap is not None and len(rows) >= cap:
            return rows[:cap]


# Sports edges (rollout step 7): candidate edges with review verdicts and links
# ════════════════════════════════════════════════════════════════════════════



_DEGRADED = threading.local()  # set by a handler whose build swallowed a failed read: do not cache it



def _ttl_by_client(seconds: float):
    """Serve a slow, read-only composition from memory for `seconds`. /api/macro and /api/weather/map took 8-10s
    per visit (2026-11-09) on data that changes hourly. Keyed on the Supabase client object itself, so a test's
    fake client never sees another's payload. Errors and degraded builds are never cached; the first visit
    after expiry still pays the full build.
    ponytail: no lock (two cold visitors both build once); add stale-while-refresh if that ever matters."""
    def deco(fn):
        state: dict = {"at": 0.0, "client": None, "value": None}

        @functools.wraps(fn)
        def wrapper(supabase=Depends(get_supabase)):
            if supabase is not None and state["client"] is supabase and time.time() - state["at"] < seconds:
                return state["value"]
            _DEGRADED.flag = False
            value = fn(supabase)
            if not getattr(_DEGRADED, "flag", False):  # a build with a failed source read is served once, never kept
                state.update(at=time.time(), client=supabase, value=value)
            return value
        return wrapper
    return deco
