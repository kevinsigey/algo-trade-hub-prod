"""The playbook: plain words -> one of a fixed set of plays -> an IdeaSpec (Kevin, 2026-10-31)."""
import json

import pytest

from tradehub.workshop import playbook
from tradehub.workshop.spec import IdeaSpec


@pytest.mark.parametrize("play", playbook.PLAYS, ids=lambda p: p.id)
def test_every_play_builds_a_valid_spec_from_its_defaults(play):
    spec = playbook.build(play.id, {}, "A play built from its defaults")
    from tradehub.workshop.events import EventSpec
    assert isinstance(spec, (IdeaSpec, EventSpec)) and spec.title == "A play built from its defaults"


WORDS = [
    ("Gold does better when stocks are down", "hedge_when_market_falls", {"tickers": ["GLD"]}),
    ("Oil as a ballast against the fall of the S&P or general index", "hedge_when_market_falls", {"tickers": ["USO"]}),
    ("buy XLE when it's oversold", "rsi_reversion", {"ticker": "XLE"}),
    ("SPY golden cross, 50/200 day moving averages", "trend_following", {"ticker": "SPY", "fast": 50, "slow": 200}),
    ("buy QQQ on a new 52-week high", "breakout", {"ticker": "QQQ", "high_days": 252}),
    ("hold defensive sectors XLV XLP XLU and MA as ballast", "ballast_basket", {"tickers": ["XLV", "XLP", "XLU", "MA"]}),
    ("buy QQQ and SPY after the Fed only when VIX is below 22", "risk_gate", {"tickers": ["QQQ", "SPY"], "vix_below": 22}),
    ("energy stocks XLE XOM CVX while crude is trending up", "commodity_trend", {"tickers": ["XLE", "XOM", "CVX"]}),
    ("gold beats stocks when 10-year yields rise", "macro_regime", {"tickers": ["GLD"], "series": "DGS10"}),
    ("buy AAPL after analyst upgrades", "analyst_momentum", {"ticker": "AAPL"}),
]


@pytest.mark.parametrize("text,play_id,values", WORDS, ids=[w[1] + ":" + w[0][:20] for w in WORDS])
def test_words_match_the_right_play_and_fill_its_slots(text, play_id, values):
    ranked = playbook.match(text)
    assert ranked and ranked[0].play.id == play_id, [(m.play.id, m.score) for m in ranked]
    got = playbook.fill(ranked[0].play, text)
    for k, v in values.items():
        assert got[k] == v, (k, got)


def test_gold_means_gld_not_the_stock_called_gold():
    assert playbook.tickers_in("long gold when SPY drops") == ["GLD", "SPY"]
    assert playbook.tickers_in("buy $GOLD the miner") == ["GOLD"]  # an explicit $ ticker is taken as written


def test_words_with_no_play_match_nothing():
    assert playbook.match("my cat likes the sunshine") == []


def _reply(content):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"model": "x/y:free", "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}]}
    return R()


def test_the_ai_only_picks_from_the_candidates_and_fills_slots(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return _reply({"play": "rsi_reversion", "values": {"ticker": "XLE", "buy_below": 30}})
    out = playbook.draft("buy XLE when it's oversold", post=post)
    schema = seen["response_format"]["json_schema"]["schema"]
    assert set(schema["properties"]["play"]["enum"]) <= {p.id for p in playbook.PLAYS} | {"none"}
    assert "rsi_reversion" in schema["properties"]["play"]["enum"] and "none" in schema["properties"]["play"]["enum"]
    c = out.spec.rules.enter.conditions[0]
    assert out.play.id == "rsi_reversion" and c.measure == "rsi" and c.threshold == 30 and out.model == "x/y:free"
    assert all(a.play.id != "rsi_reversion" for a in out.alternatives)


def test_an_out_of_range_ai_value_keeps_the_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    out = playbook.draft("buy XLE when it's oversold",
                         post=lambda *a, **k: _reply({"play": "rsi_reversion", "values": {"buy_below": 400, "ticker": "x;y"}}))
    c = out.spec.rules.enter.conditions[0]
    assert c.threshold == 35 and c.series == "XLE"


def test_the_ai_saying_none_means_no_play(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    out = playbook.draft("buy XLE when it's oversold", post=lambda *a, **k: _reply({"play": "none", "values": {}}))
    assert out is None


def test_without_a_key_the_best_word_match_drafts_it(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = playbook.draft("Gold does better when stocks are down", post=lambda *a, **k: 1 / 0)
    assert out.play.id == "hedge_when_market_falls" and out.spec.hold == ["GLD"] and out.model == "playbook"


def test_close_plays_come_back_as_alternatives(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = playbook.draft("Oil as a ballast against the fall of the S&P or general index")
    assert out.play.id == "hedge_when_market_falls"
    assert {a.play.id for a in out.alternatives} == {"ballast_basket", "commodity_trend"}
    assert all(isinstance(a.spec, IdeaSpec) for a in out.alternatives)


def test_slot_values_that_break_the_spec_fall_back_to_defaults(monkeypatch):
    # Self-review: "200/50" (fast longer than slow) or an AI pick like it must not 500 the draft.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = playbook.draft("SPY 200/50 moving average cross")
    c = out.spec.rules.enter.conditions[0]
    assert out.play.id == "trend_following" and (c.lookback_days, c.slow_days) == (50, 200)
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    out = playbook.draft("SPY golden cross", post=lambda *a, **k: _reply({"play": "trend_following",
                                                                          "values": {"fast": 150, "slow": 100}}))
    c = out.spec.rules.enter.conditions[0]
    assert (c.lookback_days, c.slow_days) == (50, 200)


def test_a_day_ma_is_a_moving_average_not_mastercard():
    assert playbook.tickers_in("hold SPY while it is above its 200-day MA") == ["SPY"]
    assert playbook.tickers_in("hold XLV and MA as ballast") == ["XLV", "MA"]


EVENT_WORDS = [
    ("XOM drifts up after earnings beats", "earnings_drift",
     {"event": "earnings", "when": "beat", "direction": "up", "tickers": ["XOM"]}),
    ("CAH falls in the days after a miss on its print", "earnings_drift", {"when": "miss", "direction": "down"}),
    ("SPY rallies on Fed days", "macro_event_day", {"event": "fomc", "tickers": ["SPY"], "window": "reaction"}),
    ("QQQ drops in the week after a hot CPI report", "macro_event_day", {"event": "cpi", "tickers": ["QQQ"]}),
    ("jobs report day moves for SPY", "macro_event_day", {"event": "jobs"}),
    ("TWLO bounces after a gap down", "gap_bounce", {"event": "gap", "when": "down", "direction": "up", "tickers": ["TWLO"]}),
]


@pytest.mark.parametrize("text,play_id,want", EVENT_WORDS, ids=[w[1] + ":" + w[0][:18] for w in EVENT_WORDS])
def test_event_words_draft_an_event_study(text, play_id, want, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = playbook.draft(text)
    assert out.play.id == play_id, [(m.play.id, m.score) for m in playbook.match(text)]
    spec = out.spec.model_dump()
    assert spec["kind"] == "event"
    for k, v in want.items():
        assert spec[k] == v, (k, spec)
