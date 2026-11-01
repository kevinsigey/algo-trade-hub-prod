"""`scanner_runs` bookkeeping: the run record Health reads to say when a job last ran.

Two properties matter. The write goes through the caller's client when one is passed (a global
fallback would let a test with a developer-local `.env` write fabricated runs to the real
database), and a completion whose start row never landed is inserted rather than silently lost.
"""
from __future__ import annotations

from tradehub.core import supabase_client


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    """Records every call; `update_rows` is what the update's execute() returns."""

    def __init__(self, update_rows=None):
        self.calls = []
        self.filters = []
        self.update_rows = update_rows if update_rows is not None else [{"id": 1}]
        self._mode = None

    def table(self, name):
        assert name == "scanner_runs"
        return self

    def insert(self, row):
        self._mode = ("insert", row)
        return self

    def update(self, row):
        self._mode = ("update", row)
        return self

    def eq(self, *a):
        self.filters.append(a)
        return self

    def execute(self):
        mode, row = self._mode
        self.calls.append((mode, row))
        return _Result(self.update_rows if mode == "update" else [{"id": 1}])


def _no_global_client(monkeypatch):
    def boom():
        raise AssertionError("the global client must not be used when one is passed")

    monkeypatch.setattr(supabase_client, "get_client", boom)


def test_start_run_writes_through_the_passed_client(monkeypatch):
    _no_global_client(monkeypatch)
    fake = _FakeClient()
    supabase_client.start_run("scan-x", ["scan"], client=fake)
    assert fake.calls == [("insert", {"run_id": "scan-x", "status": "running", "engines_run": ["scan"]})]


def test_complete_run_updates_the_matching_row(monkeypatch):
    _no_global_client(monkeypatch)
    fake = _FakeClient()
    supabase_client.complete_run("scan-x", 7, 12.345, None, client=fake)
    assert len(fake.calls) == 1
    mode, row = fake.calls[0]
    assert mode == "update"
    assert fake.filters == [("run_id", "scan-x")]  # this run's row, not every run
    assert row["status"] == "completed" and row["total_opps"] == 7 and row["error_msg"] is None
    assert row["completed_at"]


def test_complete_run_inserts_when_the_start_row_never_landed(monkeypatch):
    _no_global_client(monkeypatch)
    fake = _FakeClient(update_rows=[])
    supabase_client.complete_run("scan-x", 0, 1.0, "boom", client=fake, engines=["scan"])
    assert [mode for mode, _ in fake.calls] == ["update", "insert"]
    inserted = fake.calls[1][1]
    assert inserted["run_id"] == "scan-x" and inserted["status"] == "failed" and inserted["error_msg"] == "boom"
    # The fallback row must carry the engine, or the health reader (which filters on
    # engines_run) can never see the very marker the fallback exists to preserve.
    assert inserted["engines_run"] == ["scan"]
