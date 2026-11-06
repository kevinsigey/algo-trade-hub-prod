import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tests.workshop_fake import DB
from tradehub.guidance import edgar
from tradehub.guidance.edgar import SecRefused, earnings_filings, exhibit_url
from tradehub.guidance.universe import UNIVERSE
from tradehub.scripts.guidance_poll import run

FX = Path(__file__).parent / "fixtures" / "guidance"
SUBS = json.loads((FX / "submissions.json").read_text())
INDEX = (FX / "index.html").read_text()


def test_universe():
    assert 95 <= len(UNIVERSE) <= 101
    assert all(len(c) == 10 and c.isdigit() for c in UNIVERSE.values())
    assert UNIVERSE["AAPL"] == "0000320193"
    assert UNIVERSE["MSFT"] == "0000789019"
    assert UNIVERSE["NVDA"] == "0001045810"
    assert "GOOG" not in UNIVERSE


def test_earnings_filings_skips_non_202_and_old():
    rows = earnings_filings("0000320193", since=date(2026, 10, 1), get=lambda url: SUBS)
    assert [r["accession"] for r in rows] == ["0000320193-26-000099"]
    assert rows[0]["filed_at"] == "2026-10-30T20:31:12.000Z"
    assert earnings_filings("0000320193", since=date(2026, 10, 31), get=lambda url: SUBS) == []


def test_exhibit_url_picks_ex991():
    seen = []
    url = exhibit_url("0000320193", "0000320193-26-000024", get=lambda u: seen.append(u) or INDEX)
    assert seen == ["https://www.sec.gov/Archives/edgar/data/320193/000032019326000024/0000320193-26-000024-index.html"]
    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000024/a8-kex991q4202609262026.htm"


def test_refused_raises():
    class R:
        status_code = 429

    with pytest.raises(SecRefused):
        edgar._check(R())


def _fake_filings(cik, *, since):
    if cik != UNIVERSE["AAPL"]:
        return []
    return earnings_filings(cik, since=since, get=lambda url: SUBS)


def _exhibit(cik, accession):
    return exhibit_url(cik, accession, get=lambda u: INDEX)


def test_run_adds_once():
    supa = DB()
    now = datetime(2026, 11, 2, tzinfo=UTC)
    first = run(supa, now, filings=_fake_filings, exhibit=_exhibit)
    assert first["added"] == 1
    row = supa.db["guidance_filings"][0]
    assert row["status"] == "new" and row["ticker"] == "AAPL" and row["doc_url"].endswith("a8-kex991q4202609262026.htm")
    assert run(supa, now, filings=_fake_filings, exhibit=_exhibit)["added"] == 0
    assert len(supa.db["guidance_filings"]) == 1


def test_run_stops_on_refusal():
    calls = []

    def boom(cik, *, since):
        calls.append(cik)
        raise SecRefused("429")

    out = run(DB(), datetime(2026, 11, 2, tzinfo=UTC), filings=boom, exhibit=_exhibit)
    assert out["stopped"] == "sec refused" and out["added"] == 0 and len(calls) == 1
