"""Candidate drains never overlap (CodeRabbit on #575)."""
from __future__ import annotations

import threading

from tradehub.api.routers import valuation as val_router


def test_a_second_drain_while_one_runs_is_skipped(monkeypatch):
    from tradehub.valuation import candidates as cand_mod

    started, release, calls = threading.Event(), threading.Event(), []

    def slow_drain(supa, ds):
        calls.append(1)
        started.set()
        release.wait(5)

    monkeypatch.setattr(cand_mod, "run_candidate_debates", slow_drain)
    first = threading.Thread(target=val_router._drain_candidates, args=(None, None))
    first.start()
    assert started.wait(5)
    assert val_router._drain_candidates(None, None) is False   # overlapping: skipped
    release.set()
    first.join(5)
    assert calls == [1]
    assert val_router._drain_candidates(None, None) is True    # free again afterwards
    assert calls == [1, 1]
