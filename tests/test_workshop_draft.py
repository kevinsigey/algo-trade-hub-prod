from types import SimpleNamespace

import pytest

from tradehub.workshop.draft import MODEL, DraftUnavailable, draft_spec
from tradehub.workshop.spec import IdeaSpec

SPEC = IdeaSpec(title="Gold when rates rise", hold=["GLD"], otherwise="SPY", claim="beats_benchmark_when",
                when={"source": "fred", "series": "DGS10", "measure": "change", "op": ">", "threshold": 0.25})


class FakeClient:
    def __init__(self, response=None, error=None):
        self.calls, self.response, self.error = [], response, error
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def test_draft_returns_the_spec_and_uses_the_pinned_model():
    fake = FakeClient(SimpleNamespace(stop_reason="end_turn", parsed_output=SPEC))
    assert draft_spec("Gold does better than stocks when rates are going up.", client=fake) == SPEC
    call = fake.calls[0]
    assert call["model"] == MODEL == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "medium"} and call["output_format"] is IdeaSpec
    assert call["messages"][0]["content"].startswith("Gold does better")


def test_refusal_is_unavailable():
    fake = FakeClient(SimpleNamespace(stop_reason="refusal", parsed_output=None))
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", client=fake)
    assert e.value.reason == "refused"


def test_no_key_and_errors(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x")
    assert e.value.reason == "no_key"
    with pytest.raises(DraftUnavailable) as e:
        draft_spec("x", client=FakeClient(error=RuntimeError("boom")))
    assert e.value.reason == "error"
