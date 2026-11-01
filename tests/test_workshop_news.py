"""The news condition source (phase-2 §5.1): GDELT timelinetone parsing, the disk
cache that keeps GDELT's throttle from failing runs, loud failure with no cache, and
the spec/routing wiring that lands a basket in the engine's series dict."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from tradehub.workshop import data, news
from tradehub.workshop.spec import Condition, IdeaSpec

START = date(2026, 10, 1)
TODAY = date(2026, 10, 20)

PAYLOAD = {"timeline": [{"series": "Average Tone", "data": [
    {"date": "20261018T000000Z", "value": -2.5},
    {"date": "20261019T000000Z", "value": 1.5},
    {"date": "20261019T120000Z", "value": 2.5},  # a sub-daily bucket: resampled to the day's mean
    {"date": "20261020T000000Z", "value": 0.5},
]}]}


def _get_text(payload=PAYLOAD):
    return lambda url: json.dumps(payload)


def test_parse_timeline_resamples_buckets_to_daily_means():
    series = news.parse_timeline(PAYLOAD)
    assert list(series.index) == list(pd.to_datetime(["2026-10-18", "2026-10-19", "2026-10-20"]))
    assert series.tolist() == [-2.5, 2.0, 0.5]


def test_series_fetches_once_then_reads_the_cache(tmp_path):
    calls = {"n": 0}

    def counting(url: str) -> str:
        calls["n"] += 1
        return json.dumps(PAYLOAD)

    first = news.news_tone_series("ENERGY", START, get_text=counting, cache_dir=tmp_path, today=TODAY)
    second = news.news_tone_series("ENERGY", START, get_text=counting, cache_dir=tmp_path, today=TODAY)
    assert calls["n"] == 1  # the second read is the cache file written by the first
    pd.testing.assert_series_equal(first, second)
    assert first.loc["2026-10-19"] == 2.0


def test_a_throttled_refresh_falls_back_to_the_cache(tmp_path):
    news.news_tone_series("ENERGY", START, get_text=_get_text(), cache_dir=tmp_path, today=TODAY)

    def throttled(url: str) -> str:
        return "Please limit requests to one every 5 seconds or contact us."

    served = news.news_tone_series("ENERGY", START, get_text=throttled, cache_dir=tmp_path,
                                   today=date(2026, 10, 21))  # next day: a refresh is attempted
    assert served.loc["2026-10-20"] == 0.5  # and the cached series is what the run reads


def test_a_throttled_first_fetch_with_no_cache_raises_gdelts_words(tmp_path):
    with pytest.raises(RuntimeError, match="GDELT refused"):
        news.news_tone_series("ENERGY", START,
                              get_text=lambda url: "Please limit requests to one every 5 seconds.",
                              cache_dir=tmp_path, today=TODAY)


def test_an_unknown_basket_and_an_unparseable_answer_are_clear_errors(tmp_path):
    with pytest.raises(ValueError, match="unknown news basket"):
        news.news_tone_series("CRYPTO", START, get_text=_get_text(), cache_dir=tmp_path, today=TODAY)
    with pytest.raises(RuntimeError, match="unparseable"):
        news.news_tone_series("ENERGY", START, get_text=lambda url: "<html>nope</html>",
                              cache_dir=tmp_path, today=TODAY)


def test_spec_takes_news_with_its_three_measures_and_refuses_others():
    ok = Condition(source="news", series="ENERGY", measure="zscore", lookback_days=20, op="<", threshold=-1.0)
    assert ok.source == "news"
    with pytest.raises(ValueError, match="can't be measured on a news series"):
        Condition(source="news", series="ENERGY", measure="rsi", op=">", threshold=1.0)


def _spec_with_news() -> IdeaSpec:
    return IdeaSpec.model_validate({
        "title": "XLE when energy news tone is deeply negative",
        "claim": "beats_benchmark",
        "hold": ["XLE"], "benchmark": "SPY",
        "rules": {"enter": {"mode": "all", "conditions": [
            {"source": "news", "series": "ENERGY", "measure": "zscore",
             "lookback_days": 20, "op": "<", "threshold": -1.0}]}},
    })


def test_rule_series_routes_the_basket_to_the_news_fetcher():
    tone = pd.Series([0.1], index=pd.to_datetime(["2026-10-19"]), name="tone")
    out = data.rule_series(_spec_with_news(), START,
                           fred=lambda i, s: pd.Series(dtype=float),
                           news_fn=lambda basket, s: tone)
    assert out["ENERGY"] is tone


def test_the_drafter_schema_offers_the_news_source():
    from tradehub.workshop.draft import DraftEnvelope
    schema = json.dumps(DraftEnvelope.model_json_schema())
    assert '"news"' in schema and '"level"' in schema
