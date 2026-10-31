import json
from types import SimpleNamespace

import pytest
import requests

from tradehub.workshop.draft import MODELS, SYSTEM, DraftUnavailable, draft_spec
from tradehub.workshop.spec import IdeaSpec

SPEC = IdeaSpec(title="Gold when rates rise", hold=["GLD"], otherwise="SPY", claim="beats_benchmark_when",
                when={"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25})


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


def test_no_key_is_draft_unavailable(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    post = FakePost(reply("{}"))
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", post=post)
    assert e.value.reason == "no_key" and post.calls == []


def test_request_shape_and_parse(key):
    post = FakePost(reply(SPEC.model_dump_json()))
    spec, model = draft_spec("Gold does better than stocks when rates are going up.", post=post)
    assert spec == SPEC and model == "nvidia/nemotron-3.5-super-vl:free"
    url, kw = post.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert kw["headers"]["Authorization"] == "Bearer test-key"
    body = kw["json"]
    assert body["models"] == list(MODELS) and MODELS[0] == "nvidia/nemotron-3.5-super-vl:free"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == IdeaSpec.model_json_schema()
    assert body["messages"][0] == {"role": "system", "content": SYSTEM}
    assert body["messages"][1]["content"].startswith("Gold does better")


def test_models_env_override(key, monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODELS", "a/b:free, c/d:free")
    post = FakePost(reply(SPEC.model_dump_json()))
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
