"""Provider cycling for guidance extraction (spec 2026-11-09).

Two free pools, one fixed order: the direct OpenRouter route first
(`extract.ask_model`), the opencode CLI's gateway free models second. A pool
that rate-limits or goes down cools down and work fails over to the other
pool; a filing fails only when every pool has genuinely refused it; when no
pool can be attempted at all the call raises PoolsUnavailable and
`extract.run()` pauses with the queue untouched. No error ever produces a
record -- extraction still passes the verbatim verify() in extract.run().
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import requests

from tradehub.guidance import extract as gx

RATE_COOLDOWN_S = 1800  # 429 / quota: free pools refill slowly; probe again in half an hour
DOWN_COOLDOWN_S = 600   # 5xx / connection / timeout: transient-down probe interval
OPENCODE_TIMEOUT_S = 240
OPENCODE_MODELS = (  # the opencode gateway roster, as the call-outlook run orders it
    "opencode/deepseek-v4.1-flash-free",
    "opencode/glm-5.3-flash-free",
    "opencode/mimo-v2.6-flash-free",
)

_RATE_WORDS = re.compile(r"429|rate.?limit|quota|too many requests", re.IGNORECASE)
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class ProviderError(Exception):
    """A pool failed to produce an extraction."""


class RateLimited(ProviderError):
    """429 / quota: the pool is spent for now -- cool down and fail over."""


class ProviderDown(ProviderError):
    """5xx, connection error, timeout, CLI failure: the pool is down.

    `hard` marks a failure that cannot heal inside this process (a missing
    CLI binary): the pool stays out until the process restarts."""

    def __init__(self, message: str = "", *, hard: bool = False):
        super().__init__(message)
        self.hard = hard


class ProviderRefused(ProviderError):
    """The pool answered but unusably (unparseable, empty, content filter).
    The pool is healthy -- fail over for this filing, no cooldown."""


class AllProvidersRefused(ProviderError):
    """Every available pool was attempted and refused this filing."""


class PoolsUnavailable(ProviderError):
    """No pool could be attempted at all (cooling down / hard down).

    extract.run() checks the class attribute and pauses the run instead of
    failing filings."""

    pools_unavailable = True


def classify(exc: BaseException) -> ProviderError:
    """Map a pool ask's raw exception onto the cycling taxonomy."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, requests.HTTPError):
        status = exc.response.status_code if exc.response is not None else None
        if status == 429:
            return RateLimited(str(exc))
        if status in (401, 403) or (status is not None and status >= 500):
            return ProviderDown(str(exc))
        return ProviderRefused(str(exc))
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return ProviderDown(str(exc))
    if isinstance(exc, FileNotFoundError):
        return ProviderDown(str(exc), hard=True)
    if isinstance(exc, subprocess.TimeoutExpired):
        return ProviderDown(str(exc))
    return ProviderRefused(str(exc))


# ── pool 1: the direct OpenRouter route ──────────────────────────────────────

def ask_openrouter(text: str, *, key: str | None = None) -> gx.Envelope:
    """The shipped ask_model, with the pool recorded in the provenance."""
    env = gx.ask_model(text, key=key or "")
    env.model = f"openrouter:{env.model}"
    return env


# ── pool 2: the opencode CLI's gateway free models ───────────────────────────

def _opencode_prompt(text: str) -> str:
    schema = json.dumps(gx._envelope_tool_schema())
    return (gx.SYSTEM_PROMPT
            + "\n\nUse no tools. Reply with the JSON object only, matching this schema:\n"
            + schema + "\n\nRELEASE TEXT:\n" + text[:gx.MAX_TEXT_CHARS])


def _opencode_once(text: str, *, model: str, runner) -> gx.Envelope:
    """One `opencode run` against one gateway model (the call-outlook pattern:
    a temp folder whose opencode.json denies every tool, so release text --
    untrusted input -- can never act)."""
    work = tempfile.mkdtemp(prefix="guidance-opencode-")
    try:
        (Path(work) / "opencode.json").write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "permission": {"*": "deny", "edit": "deny", "bash": "deny", "webfetch": "deny",
                           "external_directory": "deny"},
            "tools": {"*": False}}))
        out = runner(["opencode", "run", "-m", model, "--title", "guidance-extract",
                      _opencode_prompt(text)],
                     capture_output=True, text=True, timeout=OPENCODE_TIMEOUT_S, cwd=work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    reply = _ANSI.sub("", out.stdout or "")
    if out.returncode != 0 or "Error:" in reply[-400:] or "{" not in reply:
        tail = (out.stderr or reply)[-300:]
        if _RATE_WORDS.search(tail):
            raise RateLimited(f"{model}: {tail.strip()[-200:]}")
        raise ProviderDown(f"{model}: {tail.strip()[-200:]}")
    try:
        env = gx._parse_openrouter_response(reply)
    except Exception as exc:  # noqa: BLE001 -- an unparseable reply is a refusal, not a crash
        raise ProviderRefused(f"{model}: unparseable reply") from exc
    env.model = f"opencode:{model}"
    return env


def ask_opencode(text: str, *, key: str | None = None,
                 models: tuple[str, ...] = OPENCODE_MODELS,
                 runner: Callable[..., object] = subprocess.run) -> gx.Envelope:
    """Try the gateway roster in order; the pool fails only when every model
    in it fails. The pool's verdict is its strongest failure signal:
    rate-limited beats down beats refused."""
    errors: list[ProviderError] = []
    for model in models:
        try:
            return _opencode_once(text, model=model, runner=runner)
        except BaseException as exc:  # noqa: BLE001 -- classified below, incl. runner errors
            err = classify(exc)
            if isinstance(err, ProviderDown) and err.hard:
                raise err  # no binary: the whole pool is out, don't burn the roster
            errors.append(err)
    for kind in (RateLimited, ProviderDown, ProviderRefused):
        for err in errors:
            if isinstance(err, kind):
                raise err
    raise ProviderRefused("opencode: empty model roster")


# ── the cycling asker ────────────────────────────────────────────────────────

class CyclingAsker:
    """The model callable extract.run() accepts, cycling the two pools.

    Cooldown state lives on the instance: long-lived callers (the fleet
    driver) keep one asker across rounds; the cron script's one-shot asker
    still fails over within its run."""

    def __init__(self, *, pools: list[tuple[str, Callable[..., gx.Envelope]]] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self._pools = pools if pools is not None else [
            ("openrouter", ask_openrouter), ("opencode", ask_opencode)]
        self._clock = clock
        self._cool_until: dict[str, float] = {}

    def _available(self, name: str) -> bool:
        return self._clock() >= self._cool_until.get(name, 0.0)

    def _cool(self, name: str, err: ProviderError) -> None:
        if isinstance(err, RateLimited):
            self._cool_until[name] = self._clock() + RATE_COOLDOWN_S
        elif isinstance(err, ProviderDown):
            self._cool_until[name] = (float("inf") if err.hard
                                      else self._clock() + DOWN_COOLDOWN_S)

    def __call__(self, text: str, *, key: str | None = None) -> gx.Envelope:
        attempted: list[str] = []
        skipped: list[str] = []
        errors: list[tuple[str, ProviderError]] = []
        for name, fn in self._pools:
            if name == "openrouter" and not key:
                skipped.append(name)  # no key: this pool cannot be attempted
                continue
            if not self._available(name):
                skipped.append(name)
                continue
            attempted.append(name)
            try:
                return fn(text, key=key)
            except BaseException as exc:  # noqa: BLE001 -- classified, never propagated raw
                err = classify(exc)
                errors.append((name, err))
                self._cool(name, err)
        # A filing fails ONLY on a genuine both-pools refusal: every pool was
        # attempted in this call and every attempt was a refusal. A rate
        # limit, an outage, or a pool skipped for cooling means that pool
        # never judged the filing -- the run pauses instead (spec rule,
        # learned in production 2026-11-09 when a 429 + a gateway timeout
        # wrongly failed MU's filing).
        if (attempted and not skipped
                and all(isinstance(err, ProviderRefused) for _, err in errors)):
            raise AllProvidersRefused(
                "; ".join(f"{name}: {err}" for name, err in errors))
        detail = "; ".join(
            [f"{name}: {err}" for name, err in errors]
            + [f"{name} not attempted (cooling until "
               f"{self._cool_until.get(name, 0.0):.0f})" for name in skipped])
        raise PoolsUnavailable(f"no genuine both-pool refusal ({detail})")
