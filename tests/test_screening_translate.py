import json

import pytest

from tradehub.screening.translate import TranslateUnavailable, translate


class _Resp:
    def __init__(self, content, model="stub-model"):
        self._content, self._model = content, model

    def raise_for_status(self):
        pass

    def json(self):
        return {"model": self._model,
                "choices": [{"message": {"content": self._content}}]}


def _post_returning(content):
    def post(url, headers, json, timeout):
        return _Resp(content)
    return post


def test_translate_returns_a_validated_spec(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    spec = {"name": "cheap", "universe": {"type": "index", "index": "sp500"},
            "filters": [{"fn": "pe_ratio", "op": "lt", "value": 15}]}
    out, model = translate("cheap stocks", post=_post_returning(json.dumps(spec)))
    assert out["filters"][0]["fn"] == "pe_ratio" and model == "stub-model"


def test_translate_refuses_an_invalid_spec(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    bad = {"name": "x", "universe": {"type": "index", "index": "sp500"},
           "filters": [{"fn": "not_a_function", "op": "gt", "value": 1}]}
    with pytest.raises(TranslateUnavailable):
        translate("zzz qqq", post=_post_returning(json.dumps(bad)))


def test_translate_refuses_a_non_json_reply(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    with pytest.raises(TranslateUnavailable):
        translate("zzz qqq", post=_post_returning("no spec here"))


def test_translate_without_a_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(TranslateUnavailable):
        translate("zzz qqq", post=_post_returning("{}"))


def test_openrouter_route_is_capped_at_three_models(monkeypatch):
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return _Resp(json_module_dumps())

    import json as json_module

    def json_module_dumps():
        return json_module.dumps({"name": "x", "universe": {"type": "index", "index": "sp500"},
                                  "filters": [{"fn": "pe_ratio", "op": "lt", "value": 15}]})

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    spec, _ = translate("cheap stocks", post=post)
    assert len(seen["models"]) <= 3
    assert spec["name"] == "x"


def test_translate_falls_back_to_rules_when_the_ai_raises(monkeypatch):
    def boom(url, headers, json, timeout):
        raise RuntimeError("HTTP 400")

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    spec, model = translate("stocks with strong momentum and beat earnings with positive guidance",
                            post=boom)
    fns = {(f["fn"], f["op"]) for f in spec["filters"]}
    assert ("momentum", "pct_gte") in fns
    assert ("last_print_surprise_pct", "gt") in fns
    assert ("last_print_reaction_pct", "gt") in fns
    assert model.startswith("rules")
