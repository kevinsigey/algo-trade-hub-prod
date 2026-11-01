import json
from types import SimpleNamespace

import pytest
import requests

from tradehub.workshop.draft import (ENVELOPE_NOTE, MODELS, SYSTEM, DraftEnvelope, DraftUnavailable,
                                      draft_spec)
from tradehub.workshop.spec import IdeaSpec

SPEC = IdeaSpec(title="Gold when rates rise", hold=["GLD"], otherwise="SPY", claim="beats_benchmark_when",
                when={"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25})


def env_json(spec=SPEC, requested=(), unexpressed=()):
    """An envelope reply body, the shape both drafting providers must answer in (§2.2)."""
    return json.dumps({"spec": json.loads(spec.model_dump_json()), "requested": list(requested),
                       "unexpressed": list(unexpressed)})


def claude_reply(spec=SPEC, requested=(), unexpressed=(), model="claude-sonnet-4-5", stop="tool_use",
                 status=200):
    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(f"{status} Client Error")
    content = ([{"type": "tool_use", "name": "draft_idea",
                 "input": json.loads(env_json(spec, requested, unexpressed))}]
               if stop == "tool_use" else [])
    body = {"model": model, "stop_reason": stop, "content": content}
    return SimpleNamespace(status_code=status, json=lambda: body, raise_for_status=raise_for_status)


def reply(content, finish="stop", model="nvidia/nemotron-3.5-super-vl:free", status=200):
    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(f"{status} Client Error")
    body = {"model": model, "choices": [{"finish_reason": finish, "message": {"content": content}}]}
    return SimpleNamespace(status_code=status, json=lambda: body, raise_for_status=raise_for_status)


class FakePost:
    def __init__(self, response):
        self.calls, self.response = [], response

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_DRAFT_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_DRAFT_MODEL", raising=False)


def test_no_key_is_draft_unavailable(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    post = FakePost(reply("{}"))
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", post=post)
    assert e.value.reason == "no_key" and post.calls == []


def test_request_shape_and_parse(key):
    post = FakePost(reply(env_json(requested=["GLD"])))
    spec, model, dropped, unexpressed = draft_spec("Gold does better than stocks when rates are going up.",
                                                   post=post)
    assert spec == SPEC and model == "nvidia/nemotron-3.5-super-vl:free"
    assert dropped == []  # SPY ("stocks") is the benchmark, not a dropped leg
    assert unexpressed == []
    url, kw = post.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert kw["headers"]["Authorization"] == "Bearer test-key"
    body = kw["json"]
    assert body["models"] == list(MODELS) and MODELS[0] == "nvidia/nemotron-3.5-super-vl:free"
    assert body["response_format"]["type"] == "json_schema"
    # The contract sent to the model is the generated envelope schema, never a paraphrase.
    assert body["response_format"]["json_schema"]["schema"] == DraftEnvelope.model_json_schema()
    assert body["messages"][0] == {"role": "system", "content": SYSTEM + ENVELOPE_NOTE}
    assert body["messages"][1]["content"].startswith("Gold does better")


def test_models_env_override(key, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "a/b:free, c/d:free")
    post = FakePost(reply(env_json()))
    draft_spec("x", post=post)
    assert post.calls[0][1]["json"]["models"] == ["a/b:free", "c/d:free"]


def test_bad_json_or_http_error_is_error(key):
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", post=FakePost(reply("not json")))
    assert e.value.reason == "error"
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", post=FakePost(reply("{}", status=429)))
    assert e.value.reason == "error" and "test-key" not in str(e.value)


def test_refusal(key):
    for r in (reply(json.dumps({}), finish="content_filter"), reply("")):
        with pytest.raises(DraftUnavailable) as e:
            draft_spec("x", post=FakePost(r))
        assert e.value.reason == "refused"


def test_draft_prompt_mentions_rules():
    from tradehub.workshop.draft import SYSTEM
    for word in ("rules", "enter", "exit", "all", "any", "sma_cross", "rsi", "macd", "vs_vwap", "12/26/9"):
        assert word in SYSTEM, word
    assert "while a condition holds" not in SYSTEM


def test_draft_prompt_mentions_analyst():
    from tradehub.workshop.draft import SYSTEM
    for word in ("analyst", "net_upgrades", "target_upside", "stocks only"):
        assert word in SYSTEM, word


def test_draft_prompt_mentions_spreads():
    from tradehub.workshop.draft import SYSTEM
    for word in ("spread", "A+B/C+D", "zscore", "percentile"):
        assert word in SYSTEM, word

# --- Claude first (§2.2) -----------------------------------------------------


class RouterPost:
    """One post callable serving both providers, so fallback order is observable."""

    def __init__(self, anthropic, openrouter):
        self.calls, self.anthropic, self.openrouter = [], anthropic, openrouter

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.anthropic if "anthropic" in url else self.openrouter


@pytest.fixture
def claude_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("ANTHROPIC_DRAFT_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_DRAFT_MODEL", raising=False)


def test_claude_first_forced_schema(claude_key):
    post = FakePost(claude_reply(requested=["GLD"]))
    spec, model, dropped, unexpressed = draft_spec("Gold does better when rates rise.", post=post)
    assert spec == SPEC and model == "claude-sonnet-4-5" and dropped == [] and unexpressed == []
    url, kw = post.calls[0]
    assert url == "https://api.anthropic.com/v1/messages" and len(post.calls) == 1
    assert kw["headers"]["x-api-key"] == "test-anthropic-key"
    body = kw["json"]
    assert body["tool_choice"] == {"type": "tool", "name": "draft_idea"}
    assert body["tools"][0]["input_schema"] == DraftEnvelope.model_json_schema()
    assert body["system"] == SYSTEM + ENVELOPE_NOTE


def test_claude_failure_falls_back_to_openrouter(claude_key):
    post = RouterPost(claude_reply(status=500), reply(env_json(requested=["GLD"])))
    spec, model, dropped, _ = draft_spec("Gold does better when rates rise.", post=post)
    assert spec == SPEC and model == "nvidia/nemotron-3.5-super-vl:free" and dropped == []
    assert [u for u, _ in post.calls] == ["https://api.anthropic.com/v1/messages",
                                          "https://openrouter.ai/api/v1/chat/completions"]


def test_claude_refusal_does_not_fall_back(claude_key):
    post = RouterPost(claude_reply(stop="refusal"), reply(env_json()))
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", post=post)
    assert e.value.reason == "refused" and len(post.calls) == 1


# --- Gemini first (Kevin's call 2026-11-01: no Anthropic key; free tier drafts) ---


def gemini_reply(spec=SPEC, requested=(), unexpressed=(), finish="STOP", status=200, blocked=None):
    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(f"{status} Client Error")
    body = {"candidates": [{"finishReason": finish,
                            "content": {"parts": [{"text": env_json(spec, requested, unexpressed)}]}}]}
    if blocked:
        body["promptFeedback"] = {"blockReason": blocked}
    return SimpleNamespace(status_code=status, json=lambda: body, raise_for_status=raise_for_status)


class TriPost:
    """One post callable serving all three providers, so fallback order is observable."""

    def __init__(self, gemini, anthropic, openrouter):
        self.calls, self.gemini, self.anthropic, self.openrouter = [], gemini, anthropic, openrouter

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "generativelanguage" in url:
            return self.gemini
        return self.anthropic if "anthropic" in url else self.openrouter


@pytest.fixture
def gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_DRAFT_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_gemini_first_schema_shaped(gemini_key):
    post = FakePost(gemini_reply(requested=["GLD"]))
    spec, model, dropped, unexpressed = draft_spec("Gold does better when rates rise.", post=post)
    assert spec == SPEC and model == "gemini-2.5-flash" and dropped == [] and unexpressed == []
    url, kw = post.calls[0]
    assert url == ("https://generativelanguage.googleapis.com/v1beta/models/"
                   "gemini-2.5-flash:generateContent") and len(post.calls) == 1
    assert kw["headers"]["x-goog-api-key"] == "test-gemini-key"
    body = kw["json"]
    assert body["generationConfig"]["responseJsonSchema"] == DraftEnvelope.model_json_schema()
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM + ENVELOPE_NOTE


def test_gemini_failure_falls_back_to_openrouter(gemini_key):
    post = TriPost(gemini_reply(status=500), claude_reply(), reply(env_json(requested=["GLD"])))
    spec, model, dropped, _ = draft_spec("Gold does better when rates rise.", post=post)
    assert spec == SPEC and model == "nvidia/nemotron-3.5-super-vl:free" and dropped == []
    assert [u.split("?")[0] for u, _ in post.calls] == [
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        "https://openrouter.ai/api/v1/chat/completions"]


def test_gemini_refusal_does_not_fall_back(gemini_key):
    post = TriPost(gemini_reply(blocked="SAFETY"), claude_reply(), reply(env_json()))
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", post=post)
    assert e.value.reason == "refused" and len(post.calls) == 1


def test_gemini_beats_claude_when_both_keys_set(gemini_key, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    post = TriPost(gemini_reply(requested=["GLD"]), claude_reply(), reply(env_json()))
    _, model, _, _ = draft_spec("Gold does better when rates rise.", post=post)
    assert model == "gemini-2.5-flash" and len(post.calls) == 1


def test_envelope_note_demands_capability_requests():
    # Kevin's ask: a gap must come back scoped as the specific capability to add,
    # not as a vague "unsupported" -- the format is pinned in the note itself.
    assert "capability request" in ENVELOPE_NOTE and "needs <the specific capability" in ENVELOPE_NOTE
    assert "intraday" in SYSTEM  # the daily-only limit is named so the model can scope against it


# --- The anti-truncation envelope --------------------------------------------


def test_unexplained_drop_is_loud(key):
    post = FakePost(reply(env_json(requested=["GLD", "QQQ"])))
    _, _, dropped, unexpressed = draft_spec("Gold and the Nasdaq, please.", post=post)
    assert dropped == ["QQQ"] and unexpressed == []


def test_explained_drop_is_confessed_not_dropped(key):
    post = FakePost(reply(env_json(requested=["GLD", "QQQ"],
                                   unexpressed=["QQQ left out: the words gave it no role"])))
    _, _, dropped, unexpressed = draft_spec("Gold and the Nasdaq, please.", post=post)
    assert dropped == [] and unexpressed == ["QQQ left out: the words gave it no role"]


# --- The import door ----------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient

    from tradehub.api import admin, main
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "k@example.com",
                                                                  "is_admin": True}
    return TestClient(main.app)


def test_import_returns_a_draft_for_the_confirm_screen():
    client = _client()
    r = client.post("/api/workshop/draft/import",
                    json={"spec": json.loads(SPEC.model_dump_json()), "requested": ["GLD", "QQQ"],
                          "unexpressed": []})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "import" and body["spec"]["title"] == SPEC.title
    assert body["dropped"] == ["QQQ"]  # named in requested, absent from the spec, unexplained


def test_import_rejects_a_spec_off_contract():
    client = _client()
    r = client.post("/api/workshop/draft/import", json={"spec": {"title": "x", "claim": "nope"}})
    assert r.status_code == 422 and "does not fit the contract" in r.json()["detail"]

