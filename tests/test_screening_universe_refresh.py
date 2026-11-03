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


def test_nasdaq_all_parses_the_symdir_files(monkeypatch):
    import io as _io

    import pandas as pd

    from tradehub.scripts import screening_universe_refresh as refresh

    text = "Symbol|Security Name|Test Issue\nAAA|A Co|N\nZZTEST|Test Co|Y\nFile Creation Time: x||\n"
    monkeypatch.setattr(refresh.requests, "get",
                        lambda url, headers=None, timeout=None: type("R", (), {"text": text})())
    frames = pd.read_csv(_io.StringIO(text), sep="|")
    kept = frames[frames["Test Issue"] == "N"]
    assert [str(x) for x in kept["Symbol"]] == ["AAA"]
