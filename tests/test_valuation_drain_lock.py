"""Candidate drains never overlap, across processes (CodeRabbit on #575)."""
from __future__ import annotations

import fcntl

from tradehub.valuation import candidates as cand


def test_a_drain_skips_while_another_process_holds_the_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEHUB_LOCK_DIR", str(tmp_path))
    calls = []
    monkeypatch.setattr(cand, "_run_candidate_debates", lambda *a, **k: calls.append(1) or ["ran"])
    # Another process (the cron script, or an API drain thread) holds the file lock:
    # a separate open file description, which is what a second process has.
    other = open(tmp_path / "tradehub-candidate-drain.lock", "a+")
    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert cand.run_candidate_debates(None, None) == []
        assert calls == []
    finally:
        fcntl.flock(other, fcntl.LOCK_UN)
        other.close()
    assert cand.run_candidate_debates(None, None) == ["ran"]     # free again
    assert cand.run_candidate_debates(None, None) == ["ran"]     # released after each drain
    assert calls == [1, 1]
