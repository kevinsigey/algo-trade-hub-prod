import pytest
from workshop_fake import DB

from tradehub.workshop import store


@pytest.fixture
def db():
    d = DB()
    store.create_idea(d, "one", "words")
    store.create_idea(d, "two", "words")
    return d


def test_lifecycle_timestamps_are_set_once(db):
    first = store.publish(db, 1)
    assert first["published_at"]
    with pytest.raises(store.AlreadySet):
        store.publish(db, 1)
    assert db.db["ideas"][0]["published_at"] == first["published_at"]
    live = store.go_live(db, 1, run_id=7, size_pct=20.0, gate={"status": "ready"})
    assert live["live_run_id"] == 7 and live["size_pct"] == 20.0
    with pytest.raises(store.AlreadySet):
        store.go_live(db, 1, run_id=8, size_pct=10.0, gate={})
    store.kill(db, 1)
    with pytest.raises(store.AlreadySet):
        store.kill(db, 1)


def test_live_and_published_lists(db):
    store.publish(db, 2)
    store.go_live(db, 1, run_id=1, size_pct=10.0, gate={})
    store.go_live(db, 2, run_id=2, size_pct=10.0, gate={})
    store.kill(db, 2)
    assert [i["id"] for i in store.live_ideas(db)] == [1]
    assert [i["id"] for i in store.published_ideas(db)] == [2]


def test_shadow_rows_round_trip(db):
    store.append_shadow(db, 1, [{"day": "2026-11-03", "ret": 0.01, "on": True, "bench": 0.0, "spy": 0.0},
                                {"day": "2026-11-02", "ret": 0.02, "on": True, "bench": 0.0, "spy": 0.0}])
    assert [r["day"] for r in store.shadow_days(db, 1)] == ["2026-11-02", "2026-11-03"]
    assert store.shadow_days(db, 2) == []
    assert store.append_shadow(db, 1, []) == []


def test_labels_latest_per_order_wins(db):
    store.add_label(db, "o-1", 1, "kevin")
    store.add_label(db, "o-2", 2, "kevin")
    store.add_label(db, "o-1", None, "kevin")
    assert store.labels(db) == {"o-1": None, "o-2": 2}
    assert [h["idea_id"] for h in store.label_history(db)["o-1"]] == [1, None]
