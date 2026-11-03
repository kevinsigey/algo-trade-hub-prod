"""The Workshop dashboard totals (Kevin, 2026-11-02): ideas by lifecycle,
saved-vs-total runs with the latest-verdict tally, fill attribution with the
needs-label count (no tag and no relabel), and closed P&L grouped by idea."""

from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase
from tradehub.portfolio import service


class FakeQuery:
    def __init__(self, store, table):
        self.store, self.table, self.filters = store, table, []

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def is_(self, col, val):
        self.filters.append((col, None if val == "null" else val))
        return self

    def order(self, col, desc=False):
        self.col, self.desc = col, desc
        return self

    def insert(self, row):
        rows = self.store.setdefault(self.table, [])
        row = {**row, "id": max([r.get("id", 0) for r in rows], default=0) + 1}
        rows.append(row)
        self.inserted = [row]
        return self

    def update(self, values):
        self.updates = values
        return self

    def delete(self):
        self.deleting = True
        return self

    def execute(self):
        if hasattr(self, "inserted"):
            return type("R", (), {"data": self.inserted})()
        rows = [r for r in self.store.get(self.table, [])
                if all(r.get(c) == v for c, v in self.filters)]
        if getattr(self, "updates", None):
            for r in rows:
                r.update(self.updates)
        if getattr(self, "col", None):
            rows.sort(key=lambda r: r.get(self.col) or 0, reverse=getattr(self, "desc", False))
        return type("R", (), {"data": rows})()


class FakeSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return FakeQuery(self.store, name)


STORE = {
    "ideas": [
        {"id": 1, "title": "Live one", "created_at": "2026-11-01", "published_at": "2026-11-01",
         "tracked_at": "2026-11-01", "live_at": "2026-11-02", "killed_at": None},
        {"id": 2, "title": "Tracking one", "created_at": "2026-11-02", "published_at": "2026-11-02",
         "tracked_at": "2026-11-02", "live_at": None, "killed_at": None},
        {"id": 3, "title": "Draft one", "created_at": "2026-11-02", "published_at": None,
         "tracked_at": None, "live_at": None, "killed_at": None},
    ],
    "idea_runs": [
        {"id": 11, "idea_id": 1, "variation": 1, "verdict": "PASS", "created_at": "2026-11-01T10:00:00Z"},
        {"id": 12, "idea_id": 1, "variation": 2, "verdict": "PASS", "created_at": "2026-11-02T10:00:00Z"},
        {"id": 13, "idea_id": 2, "variation": 1, "verdict": "FAIL", "created_at": "2026-11-02T11:00:00Z"},
        {"id": 14, "idea_id": 3, "variation": 1, "verdict": "PASS", "created_at": "2026-11-02T12:00:00Z"},
    ],
    "idea_run_saves": [{"run_id": 11}, {"run_id": 12}, {"run_id": 13}],
    "book_activations": [{"book": "big", "idea_id": 2, "live_at": "2026-11-02", "killed_at": None}],
    "screens": [{"id": 1, "name": "s", "spec": {}, "last_run": None, "promoted_idea_id": 9},
                {"id": 2, "name": "t", "spec": {}, "last_run": None, "promoted_idea_id": None}],
    "manual_actions": [{"book": "main", "state": "open", "created_at": "2026-11-02"}],
    "order_labels": [{"id": 1, "order_id": "o3", "idea_id": None}],
}


def test_dashboard_totals(monkeypatch):
    fake = FakeSupabase({k: [dict(r) for r in v] for k, v in STORE.items()})
    main.app.dependency_overrides[main.admin.require_admin] = lambda: {"email": "k@example.com"}
    main.app.dependency_overrides[get_supabase] = lambda: fake
    fills = [
        {"order_id": "o1", "idea_id": 1, "idea": "Live one"},     # tagged to an idea
        {"order_id": "o2", "idea_id": None, "idea": None},          # machine order: tag ext- -> manual, decided by its tag? no: ext has no idea tag
        {"order_id": "o3", "idea_id": None, "idea": None},          # relabelled to manual -> decided
        {"order_id": "o4", "idea_id": None, "idea": None},          # nothing at all -> needs a label
    ]
    client_ids = {"o1": "idea-1-auto-20261102", "o2": "ext-abc", "o3": "manual-xyz", "o4": None}
    monkeypatch.setattr(service, "tagged_fills", lambda supa, public=True: (fills, client_ids))
    monkeypatch.setattr(service, "closed", lambda supa, book_name=None: {
        "state": "live", "trades": [{"idea": "Live one", "pnl": 120.0}, {"idea": "Live one", "pnl": -20.0},
                                    {"idea": None, "pnl": 30.0}]})
    try:
        body = TestClient(main.app).get("/api/workshop/dashboard").json()
    finally:
        main.app.dependency_overrides.pop(main.admin.require_admin, None)
        main.app.dependency_overrides.pop(get_supabase, None)
    assert body["ideas"] == {"total": 3, "live": 1, "live_big": 1, "tracking": 1,
                             "published": 0, "draft": 1, "killed": 0}
    assert body["runs"]["total"] == 4 and body["runs"]["saved"] == 3
    assert body["runs"]["latest_verdicts"] == {"PASS": 1, "FAIL": 1}
    assert [r["idea_id"] for r in body["runs"]["recent"]] == [2, 1, 1]
    assert body["fills"]["total"] == 4 and body["fills"]["attributed"] == 1
    assert body["fills"]["needs_label"] == 1  # only o4: no tag, no label, placed outside the hub
    assert body["fills"]["closed_pnl_by_idea"] == [
        {"idea": "Live one", "pnl": 100.0, "trades": 2},
        {"idea": "Manual / mirror", "pnl": 30.0, "trades": 1}]
    assert body["screens"] == {"total": 2, "promoted": 1}
    assert body["manual_actions_open"] == 1
