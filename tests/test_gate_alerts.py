"""gate_switch alerts: written once per (version, event) into the
watcher_alerts outbox, watch_id NULL, and fail-soft — a broken outbox
must never break the scorer that called it."""
from __future__ import annotations

from types import SimpleNamespace

from tradehub.gate_alerts import write_gate_alert


class _Q:
    def __init__(self, db):
        self.db, self.filters, self.inserted = db, {}, None

    def select(self, *_a):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def insert(self, row):
        self.inserted = row
        return self

    def execute(self):
        if self.inserted is not None:
            self.db.append(self.inserted)
            return SimpleNamespace(data=[self.inserted])
        rows = [r for r in self.db
                if all(r.get(k) == v for k, v in self.filters.items())]
        return SimpleNamespace(data=rows)


class _Client:
    def __init__(self):
        self.rows: list[dict] = []

    def table(self, _name):
        return _Q(self.rows)


def _write(client, event="eligible"):
    return write_gate_alert(client, family="fifteen",
                            version="v4-edge20-shadow", event=event,
                            title="t", body="b", evidence={"trades": 120})


def test_write_once_then_deduped():
    client = _Client()
    assert _write(client) is True
    assert _write(client) is False  # same version + event: announced once
    assert _write(client, event="killed") is True
    assert len(client.rows) == 2
    row = client.rows[0]
    assert row["kind"] == "gate_switch" and row["watch_id"] is None
    assert row["status"] == "pending"
    assert row["evidence"]["version"] == "v4-edge20-shadow"
    assert row["evidence"]["trades"] == 120


def test_fail_soft_on_a_broken_client():
    class Broken:
        def table(self, _name):
            raise RuntimeError("db down")

    assert _write(Broken()) is False
