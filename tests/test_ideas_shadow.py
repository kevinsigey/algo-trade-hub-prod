from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from workshop_fake import DB

from tradehub.scripts import ideas_shadow
from tradehub.workshop import store

SPEC = {"title": "AAA beats SPY", "hold": ["AAA"], "claim": "beats_benchmark", "start": "2024-01-02"}
IDX = pd.bdate_range("2024-01-02", "2026-11-13")


def prices(gap: str | None = None):
    rng = np.random.default_rng(1)
    frame = pd.DataFrame({t: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, len(IDX))) for t in
                          ("AAA", "SPY", "QQQ", "IWM")}, index=IDX)
    if gap:
        frame.loc[pd.Timestamp(gap), "AAA"] = np.nan
    return frame


def fake_closes(frame):
    def closes(tickers, start):
        return frame[[t for t in tickers if t in frame]]
    return closes


@pytest.fixture
def db():
    d = DB()
    store.create_idea(d, "AAA beats SPY", "words")
    d.table("idea_runs").insert({"idea_id": 1, "variation": 1, "spec": SPEC, "verdict": "PASS",
                                 "result": {}, "data_end": "2026-10-29"}).execute()
    d.db["ideas"][0].update({"live_at": "2026-11-02T15:00:00+00:00", "live_run_id": 1, "size_pct": 10})
    return d


def evening(day: str) -> datetime:
    return datetime.fromisoformat(f"{day}T23:00:00+00:00").astimezone(UTC)


def test_first_run_starts_the_day_after_go_live(db):
    out = ideas_shadow.run(evening("2026-11-04"), db, closes=fake_closes(prices()), fred=None)
    assert out == {1: 2}
    assert [r["day"] for r in store.shadow_days(db, 1)] == ["2026-11-03", "2026-11-04"]


def test_gap_is_filled_in_order_and_rerun_adds_nothing(db):
    closes = fake_closes(prices())
    ideas_shadow.run(evening("2026-11-03"), db, closes=closes, fred=None)
    assert ideas_shadow.run(evening("2026-11-10"), db, closes=closes, fred=None) == {1: 5}
    assert [r["day"] for r in store.shadow_days(db, 1)][-1] == "2026-11-10"
    assert ideas_shadow.run(evening("2026-11-10"), db, closes=closes, fred=None) == {1: 0}


def test_no_close_means_no_row(db):
    ideas_shadow.run(evening("2026-11-06"), db, closes=fake_closes(prices(gap="2026-11-04")), fred=None)
    assert "2026-11-04" not in [r["day"] for r in store.shadow_days(db, 1)]


def test_killed_idea_gets_nothing(db):
    db.db["ideas"][0]["killed_at"] = "2026-11-03T15:00:00+00:00"
    assert ideas_shadow.run(evening("2026-11-06"), db, closes=fake_closes(prices()), fred=None) == {}


def test_today_counts_only_after_the_close(db):
    midday = datetime.fromisoformat("2026-11-04T16:00:00+00:00")
    ideas_shadow.run(midday, db, closes=fake_closes(prices()), fred=None)
    assert [r["day"] for r in store.shadow_days(db, 1)] == ["2026-11-03"]
