"""Triggering a debate (feed spec §4): manual only, one ticker, capped at 10 runs a
day. The framework runs in its OWN environment via a subprocess -- this package never
imports it (the fence, test-enforced). Every outcome is stored as an artifact,
including failures: a run that cannot start is a failed_error record, never a
silently dropped request."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from tradehub.agents import importer, store
from tradehub.agents.schema import RunRecord

CT = ZoneInfo("America/Chicago")
MAX_RUNS_PER_DAY = 10
TIMEOUT_SECONDS = 1800
_RUNNER = Path(__file__).parent / "framework_runner.py"


def framework_python() -> Path | None:
    """The isolated env's interpreter: TRADEHUB_AGENTS_PYTHON, else the sibling venv
    this package's setup creates (tradehub/agents/.venv). None = not installed."""
    raw = os.getenv("TRADEHUB_AGENTS_PYTHON", "").strip()
    if raw:
        return Path(raw)
    sibling = Path(__file__).parent / ".venv" / "bin" / "python"
    return sibling if sibling.exists() else None


def _stamps(now: datetime) -> tuple[str, str, str]:
    return (now.astimezone(CT).isoformat(timespec="seconds"), now.astimezone(UTC).isoformat(timespec="seconds"),
            now.astimezone(CT).strftime("%Y%m%d-%H%M%S"))


def _store_failure(ticker: str, as_of: str, historical: bool, error: str, now: datetime) -> RunRecord:
    run_at_ct, run_at_utc, slug = _stamps(now)
    record = RunRecord(run_id=f"{ticker.lower()}-{slug}", ticker=ticker, run_at_ct=run_at_ct,
                       run_at_utc=run_at_utc, as_of_date=as_of, historical=historical,
                       status="failed_error", error=error)
    store.save_run(record, f"# Agent debate: {ticker}\n\nRun failed: {error}\n")
    return record


def run_debate(ticker: str, as_of: str | None = None, *, now: datetime | None = None,
               latest_session: str | None = None, spawn=subprocess.run) -> RunRecord:
    now = now or datetime.now(UTC)
    ticker = ticker.strip().upper()
    as_of = as_of or latest_session or now.astimezone(CT).date().isoformat()
    historical = bool(latest_session and as_of < latest_session)
    today = now.astimezone(CT).date().isoformat()
    todays = [r for r in store.list_runs() if r.run_at_ct.startswith(today)]
    if len(todays) >= MAX_RUNS_PER_DAY:
        return _store_failure(ticker, as_of, historical,
                              f"daily cap reached ({MAX_RUNS_PER_DAY} runs/day)", now)
    python = framework_python()
    if python is None:
        return _store_failure(ticker, as_of, historical,
                              "framework not installed: create the isolated env "
                              "(tradehub/agents/requirements.txt) or set TRADEHUB_AGENTS_PYTHON", now)
    try:
        proc = spawn([str(python), str(_RUNNER), ticker, as_of], capture_output=True, text=True,
                     timeout=TIMEOUT_SECONDS, env=dict(os.environ))
    except subprocess.TimeoutExpired:
        return _store_failure(ticker, as_of, historical,
                              f"framework run timed out after {TIMEOUT_SECONDS}s", now)
    except Exception as exc:  # noqa: BLE001 -- a spawn failure is a stored failure, not a crash
        return _store_failure(ticker, as_of, historical, f"framework spawn failed: {type(exc).__name__}", now)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or ["unknown framework error"]
        return _store_failure(ticker, as_of, historical, f"framework error: {tail[0][:300]}", now)
    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return _store_failure(ticker, as_of, historical, "framework returned unreadable output", now)
    run_at_ct, run_at_utc, slug = _stamps(now)
    record = importer.build_record(raw, run_id=f"{ticker.lower()}-{slug}", run_at_ct=run_at_ct,
                                   run_at_utc=run_at_utc, as_of_date=as_of, historical=historical)
    store.save_run(record, importer.build_report(raw))
    return record
