"""Provider cycling for guidance extraction (spec 2026-11-09): two free pools,
failover with cooldowns, a filing fails only when both pools refuse it, and a
run pauses -- failing nothing -- when no pool can be attempted at all."""

import pytest
import requests

from tradehub.guidance import extract as gx
from tradehub.guidance import providers as pv


def _env(model="some/free-model:free"):
    return gx.Envelope(no_guidance=False, items=[], model=model)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=resp)


# ── classification ───────────────────────────────────────────────────────────

def test_429_is_rate_limited_and_5xx_and_timeouts_are_down():
    assert isinstance(pv.classify(_http_error(429)), pv.RateLimited)
    assert isinstance(pv.classify(_http_error(503)), pv.ProviderDown)
    assert isinstance(pv.classify(_http_error(401)), pv.ProviderDown)
    assert isinstance(pv.classify(requests.ConnectionError("refused")), pv.ProviderDown)
    assert isinstance(pv.classify(requests.Timeout("slow")), pv.ProviderDown)


def test_an_unusable_answer_is_refused_not_a_cooldown():
    assert isinstance(pv.classify(RuntimeError("model returned no guidance")), pv.ProviderRefused)
    assert isinstance(pv.classify(ValueError("bad json")), pv.ProviderRefused)


# ── the cycling asker ────────────────────────────────────────────────────────

def test_a_429_fails_over_to_the_second_pool_with_provenance():
    calls = []

    def pool_a(text, key=None):
        calls.append("a")
        raise _http_error(429)

    def pool_b(text, key=None):
        calls.append("b")
        return _env("opencode/deepseek-v4.1-flash-free")

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=FakeClock())
    env = asker("release text", key="k")
    assert calls == ["a", "b"] and env.model == "opencode/deepseek-v4.1-flash-free"


def test_a_rate_limited_pool_is_not_retried_during_its_cooldown():
    calls = {"a": 0, "b": 0}

    def pool_a(text, key=None):
        calls["a"] += 1
        raise _http_error(429)

    def pool_b(text, key=None):
        calls["b"] += 1
        return _env()

    clock = FakeClock()
    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=clock)
    asker("one", key="k")
    asker("two", key="k")
    assert calls == {"a": 1, "b": 2}  # second call skipped the cooling pool entirely
    clock.t += pv.RATE_COOLDOWN_S + 1
    asker("three", key="k")
    assert calls["a"] == 2  # and tries it again once the cooldown lapses


def test_a_refusal_does_not_cool_the_pool_down():
    calls = {"a": 0}

    def pool_a(text, key=None):
        calls["a"] += 1
        if calls["a"] == 1:
            raise RuntimeError("model returned no guidance")
        return _env()

    def pool_b(text, key=None):
        return _env("opencode/glm-5.3-flash-free")

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=FakeClock())
    asker("one", key="k")
    assert asker("two", key="k").model == "some/free-model:free" and calls["a"] == 2


def test_both_pools_refusing_fails_the_filing_and_names_both():
    def pool_a(text, key=None):
        raise ValueError("unparseable reply")  # classifies as a refusal

    def pool_b(text, key=None):
        raise pv.ProviderRefused("opencode: unparseable reply")

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=FakeClock())
    with pytest.raises(pv.AllProvidersRefused) as ei:
        asker("text", key="k")
    assert "openrouter" in str(ei.value) and "opencode" in str(ei.value)


def test_a_rate_limit_plus_a_down_is_a_pause_not_a_failure():
    # The production MU case (2026-11-09): OpenRouter 429 + the opencode pool
    # timing out. Neither pool REFUSED the filing, so it must not fail --
    # the run pauses and the filing stays new for a later cycle.
    def pool_a(text, key=None):
        raise _http_error(429)

    def pool_b(text, key=None):
        raise pv.ProviderDown("opencode: timed out")

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=FakeClock())
    with pytest.raises(pv.PoolsUnavailable):
        asker("text", key="k")


def test_a_rate_limit_plus_a_refusal_is_a_pause_not_a_failure():
    # One pool never got to judge the filing (quota), so a refusal from the
    # other pool alone is not a both-pools refusal.
    def pool_a(text, key=None):
        raise _http_error(429)

    def pool_b(text, key=None):
        raise pv.ProviderRefused("opencode: unparseable reply")

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=FakeClock())
    with pytest.raises(pv.PoolsUnavailable):
        asker("text", key="k")


def test_a_refusal_while_the_other_pool_cools_is_a_pause():
    clock = FakeClock()

    def pool_a(text, key=None):
        raise _http_error(429)

    def pool_b(text, key=None):
        raise pv.ProviderRefused("opencode: unparseable reply")

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=clock)
    with pytest.raises(pv.PoolsUnavailable):
        asker("one", key="k")  # a rate-limits (cools), b refuses: pause, not fail
    with pytest.raises(pv.PoolsUnavailable):
        asker("two", key="k")  # a still cooling (never attempted), b refuses: pause


def test_no_attemptable_pool_is_unavailable_not_a_refusal():
    def pool_a(text, key=None):
        raise _http_error(429)

    def pool_b(text, key=None):
        raise pv.ProviderDown("opencode binary missing", hard=True)

    asker = pv.CyclingAsker(pools=[("openrouter", pool_a), ("opencode", pool_b)], clock=FakeClock())
    with pytest.raises(pv.PoolsUnavailable):
        asker("one", key="k")  # both attempted, both unavailable-class: a pause
    with pytest.raises(pv.PoolsUnavailable):
        asker("two", key="k")  # now a is cooling and b is hard down: nothing to attempt


# ── run() integration ────────────────────────────────────────────────────────

def _two_filing_db():
    from workshop_fake import DB

    db = DB()
    db.table("guidance_filings").insert([
        {"accession": "a1", "ticker": "ACME", "cik": "1", "doc_url": "u1", "status": "new"},
        {"accession": "a2", "ticker": "BETA", "cik": "2", "doc_url": "u2", "status": "new"},
    ]).execute()
    return db


def _no_consensus(t, m, p):
    return None, None, None


def test_a_paused_run_fails_nothing_and_leaves_the_queue_new():
    db = _two_filing_db()

    def model(text, key=None):
        raise pv.PoolsUnavailable("all provider pools are cooling down")

    out = gx.run(db, fetch=lambda u: "<p>x</p>", model=model, consensus=_no_consensus, key="k")
    assert "paused" in out
    assert all(r["status"] == "new" for r in db.db["guidance_filings"])
    assert not db.db.get("guidance_records")


def test_a_filing_failed_by_both_pools_says_so():
    db = _two_filing_db()

    def model(text, key=None):
        raise pv.AllProvidersRefused("openrouter: 429; opencode: down")

    out = gx.run(db, fetch=lambda u: "<p>x</p>", model=model, consensus=_no_consensus, key="k", limit=1)
    assert out["failed"] == 1
    row = db.db["guidance_filings"][0]
    assert row["status"] == "failed" and "opencode" in row["error"]


# ── the opencode pool ────────────────────────────────────────────────────────

class _Proc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def test_the_opencode_pool_reads_the_json_object_from_its_stdout():
    body = '{"no_guidance": true, "items": []}'
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return _Proc(f"\n> build · deepseek\n\n{body}\n")

    env = pv.ask_opencode("release", models=["opencode/deepseek-v4.1-flash-free"], runner=runner)
    assert env.no_guidance and env.model == "opencode:opencode/deepseek-v4.1-flash-free"
    assert seen["cmd"][:3] == ["opencode", "run", "-m"]


def test_a_missing_opencode_binary_is_a_hard_down():
    def runner(cmd, **kw):
        raise FileNotFoundError("opencode")

    with pytest.raises(pv.ProviderDown) as ei:
        pv.ask_opencode("release", models=["opencode/deepseek-v4.1-flash-free"], runner=runner)
    assert ei.value.hard


def test_an_opencode_timeout_is_down_and_a_rate_word_is_rate_limited():
    import subprocess

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))

    with pytest.raises(pv.ProviderDown):
        pv.ask_opencode("release", models=["opencode/deepseek-v4.1-flash-free"], runner=slow)

    def limited(cmd, **kw):
        return _Proc("", returncode=1, stderr="Error: 429 rate limit exceeded for this model")

    with pytest.raises(pv.RateLimited):
        pv.ask_opencode("release", models=["opencode/deepseek-v4.1-flash-free"], runner=limited)


def test_the_opencode_pool_tries_its_next_model_before_failing():
    body = '{"no_guidance": true, "items": []}'
    tried = []

    def runner(cmd, **kw):
        tried.append(cmd[3])
        if "deepseek" in cmd[3]:
            return _Proc("", returncode=1, stderr="boom")
        return _Proc(body)

    env = pv.ask_opencode("release", models=["opencode/deepseek-v4.1-flash-free",
                                             "opencode/glm-5.3-flash-free"], runner=runner)
    assert tried == ["opencode/deepseek-v4.1-flash-free", "opencode/glm-5.3-flash-free"]
    assert env.model == "opencode:opencode/glm-5.3-flash-free"


# ── the openrouter pool keeps its provenance ─────────────────────────────────

def test_the_openrouter_pool_prefixes_its_provenance(monkeypatch):
    monkeypatch.setattr(pv.gx, "ask_model", lambda text, key=None: _env("nvidia/nemotron:free"))
    env = pv.ask_openrouter("release", key="k")
    assert env.model == "openrouter:nvidia/nemotron:free"
