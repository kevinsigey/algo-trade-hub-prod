"""The universe refresh reads Wikipedia constituent tables whose ticker
header differs by page ("Symbol" on the S&P page, formerly "Ticker" on the
Nasdaq-100 page): either header must resolve."""

import pandas as pd

from tradehub.scripts import screening_universe_refresh as refresh


def test_wiki_tickers_accepts_either_header(monkeypatch):
    frame = pd.DataFrame({"Symbol": ["AAA", "BRK.B"], "Name": ["A Co", "B Co"]})
    monkeypatch.setattr(refresh.requests, "get",
                        lambda url, headers=None, timeout=None: type("R", (), {"text": "<html/>"})())
    monkeypatch.setattr(refresh.pd, "read_html", lambda _: [frame])
    assert refresh._wiki_tickers("https://example.invalid", "Ticker") == ["AAA", "BRK-B"]
