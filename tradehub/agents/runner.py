"""Triggering a debate (feed spec §4): manual only, one ticker, capped at 10 runs a
day. The framework runs in its OWN environment via a subprocess -- this package never
imports it (the fence, test-enforced). Every outcome is stored as an artifact,
including failures: a run that cannot start is a failed_error record, never a
silently dropped request."""

from __future__ import annotations

import json
import os
import re
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


def _root_cause(stderr: str | None) -> str:
    """The stored failure reason. A framework traceback's LAST line is the
    LangGraph wrapper ("During task with name 'News Analyst'..."), which names
    the stage, not the cause -- the deepest exception line above it is the
    cause. Quota exhaustion (the failure Kevin will actually hit on the free
    tier) gets a plain sentence instead of a raw API dump."""
    text = stderr or ""
    if "RESOURCE_EXHAUSTED" in text or "generate_content_free_tier_requests" in text:
        return ("Gemini free-tier daily quota exhausted (20 requests/day for this model; "
                "the Workshop drafter shares it) -- debates resume after Google's daily reset")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    exc = [ln for ln in lines if re.match(r"^[\w.]+(Error|Exception|Timeout|Interrupt):", ln)]
    if exc:
        return f"framework error: {exc[-1][:300]}"
    tail = [ln for ln in lines if not ln.startswith("During task")] or lines
    return f"framework error: {(tail[-1] if tail else 'unknown framework error')[:300]}"


# Signatures of "the primary provider is unavailable" (quota, rate limit,
# outage) as opposed to "the debate itself failed". Only the first kind earns
# the OpenRouter fallback retry.
_PROVIDER_DOWN = ("RESOURCE_EXHAUSTED", "generate_content_free_tier_requests",
                  "429", "RateLimit", "rate_limit", "503", "UNAVAILABLE",
                  "APIConnectionError", "ConnectError", "InternalServerError")


def _provider_down(stderr: str | None) -> bool:
    text = stderr or ""
    return any(sig in text for sig in _PROVIDER_DOWN)


def _fallback_env() -> dict[str, str] | None:
    """The OpenRouter fallback environment for the framework subprocess, or
    None when it cannot apply: no OpenRouter key, or the primary is already
    the OpenAI-compatible endpoint. OpenRouter is OpenAI-compatible, so the
    framework's "openai" provider + backend_url reaches it, with the
    OpenRouter key riding as OPENAI_API_KEY. The model is a free REASONING
    model (Kevin's rule, 2026-11-02): the shared list's head unless
    TRADEHUB_AGENTS_FALLBACK_MODEL overrides it."""
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        return None
    if os.getenv("TRADEHUB_AGENTS_PROVIDER", "").strip().lower() in ("openai", "openrouter"):
        return None
    from tradehub.workshop.draft import _models
    env = dict(os.environ)
    env.update({
        "TRADEHUB_AGENTS_PROVIDER": "openai",
        "TRADEHUB_AGENTS_MODEL": os.getenv("TRADEHUB_AGENTS_FALLBACK_MODEL", "").strip() or _models()[0],
        "TRADEHUB_AGENTS_BACKEND_URL": "https://openrouter.ai/api/v1",
        "OPENAI_API_KEY": key,
    })
    return env


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
        # Primary provider unavailable (quota/outage): one retry on the
        # OpenRouter free reasoning models before the failure is stored.
        fallback = _fallback_env() if _provider_down(proc.stderr) else None
        if fallback is not None:
            try:
                retry = spawn([str(python), str(_RUNNER), ticker, as_of], capture_output=True,
                              text=True, timeout=TIMEOUT_SECONDS, env=fallback)
            except Exception:  # noqa: BLE001 -- a failed retry falls through to the stored failure
                retry = None
            if retry is not None and retry.returncode == 0:
                proc = retry
            elif retry is not None:
                return _store_failure(ticker, as_of, historical,
                                      f"{_root_cause(proc.stderr)} OpenRouter fallback also failed: "
                                      f"{_root_cause(retry.stderr)}", now)
        if proc.returncode != 0:
            return _store_failure(ticker, as_of, historical, _root_cause(proc.stderr), now)
    try:
        raw = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return _store_failure(ticker, as_of, historical, "framework returned unreadable output", now)
    run_at_ct, run_at_utc, slug = _stamps(now)
    record = importer.build_record(raw, run_id=f"{ticker.lower()}-{slug}", run_at_ct=run_at_ct,
                                   run_at_utc=run_at_utc, as_of_date=as_of, historical=historical)
    store.save_run(record, importer.build_report(raw))
    return record
