"""Machine API keys, step 1 (phase-2 spec §1.2/§1.5/§1.6): the lifecycle, nothing else.

The properties that matter: the plaintext exists only in create's return value -- the stored
row holds its SHA-256 hash and no response ever carries even the hash; verification fails
closed (malformed, unknown and revoked are all the same None); revocation is final (the
first timestamp stands); and every lifecycle step writes its audit event. The /api/v1 routes
do not exist yet -- auth-matrix tests for them land with step 2.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from workshop_fake import DB

from tradehub.api import admin, machine_keys, main
from tradehub.api.dependencies import get_supabase

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return DB()


def _create(db, label="mac scripts", scopes=("orders:place",), **caps):
    return machine_keys.create_key(db, label, list(scopes), **caps)


def test_create_shows_the_key_once_and_stores_only_its_hash(db):
    row, plaintext = _create(db)
    assert plaintext.startswith("thk_") and len(plaintext) == 36
    stored = db.db[machine_keys.KEYS][0]
    assert stored["key_hash"] == machine_keys.hash_key(plaintext)
    assert plaintext not in stored.values()
    assert "key_hash" not in row  # not even the hash leaves the server


def test_the_hash_cannot_be_walked_back_to_a_key(db):
    """The stored value is a SHA-256 of a 128-bit random key: asserting the shape is the
    practical form of 'cannot be reversed' -- the input space is the token_hex space."""
    _, plaintext = _create(db)
    stored = db.db[machine_keys.KEYS][0]
    assert len(bytes.fromhex(plaintext[4:])) == 16
    assert stored["key_hash"] != plaintext


def test_create_validates_scopes_and_label(db):
    with pytest.raises(ValueError):
        machine_keys.create_key(db, "x", ["orders:everything"])
    with pytest.raises(ValueError):
        machine_keys.create_key(db, "x", [])
    with pytest.raises(ValueError):
        machine_keys.create_key(db, "  ", ["orders:place"])
    with pytest.raises(ValueError):
        machine_keys.create_key(db, "x", ["orders:place"], max_qty=0)
    assert db.db.get(machine_keys.KEYS, []) == []


def test_verify_accepts_a_live_key_and_rejects_everything_else(db):
    row, plaintext = _create(db, scopes=("orders:place", "portfolio:read"))
    got = machine_keys.verify_key(db, plaintext, now=NOW)
    assert got["id"] == row["id"] and got["scopes"] == ["orders:place", "portfolio:read"]
    assert machine_keys.verify_key(db, "thk_" + "0" * 32, now=NOW) is None  # well-formed, unknown
    assert machine_keys.verify_key(db, "not a key", now=NOW) is None
    assert machine_keys.verify_key(db, None, now=NOW) is None
    assert machine_keys.verify_key(db, "", now=NOW) is None


def test_verify_writes_last_used_at_most_once_a_minute(db):
    row, plaintext = _create(db)
    machine_keys.verify_key(db, plaintext, now=NOW)
    first = db.db[machine_keys.KEYS][0]["last_used_at"]
    assert first == NOW.isoformat()
    machine_keys.verify_key(db, plaintext, now=NOW + timedelta(seconds=30))
    assert db.db[machine_keys.KEYS][0]["last_used_at"] == first
    machine_keys.verify_key(db, plaintext, now=NOW + timedelta(seconds=61))
    assert db.db[machine_keys.KEYS][0]["last_used_at"] == (NOW + timedelta(seconds=61)).isoformat()


def test_a_revoked_key_fails_verification_and_revocation_is_final(db):
    row, plaintext = _create(db)
    out = machine_keys.revoke_key(db, row["id"], now=NOW)
    assert out["revoked_at"] == NOW.isoformat()
    assert machine_keys.verify_key(db, plaintext, now=NOW) is None
    again = machine_keys.revoke_key(db, row["id"], now=NOW + timedelta(days=1))
    assert again["revoked_at"] == NOW.isoformat()  # the first timestamp stands
    assert machine_keys.revoke_key(db, 999) is None


def test_lifecycle_writes_audit_events(db):
    row, _ = _create(db)
    machine_keys.revoke_key(db, row["id"], now=NOW)
    events = machine_keys.recent_events(db, row["id"])
    assert all(e["route"] == "admin/keys" for e in events)
    outcomes = {e["outcome"] for e in events}
    assert outcomes == {"created", "revoked"}
    assert all(e["detail"] == "mac scripts" for e in events)


def test_recent_events_are_newest_first_and_capped(db):
    for i in range(3):
        db.table(machine_keys.EVENTS).insert({
            "key_id": 7, "route": "/api/v1/orders", "outcome": "read",
            "at": f"2026-11-01T0{i}:00:00+00:00", "detail": None, "client_order_id": None,
        }).execute()
    events = machine_keys.recent_events(db, 7, limit=2)
    assert [e["at"] for e in events] == ["2026-11-01T02:00:00+00:00", "2026-11-01T01:00:00+00:00"]


# ── the admin routes: session-gated, key shown once, hash never ──────────────────────────

@pytest.fixture
def api():
    db = DB()
    main.app.dependency_overrides[get_supabase] = lambda: db
    main.app.dependency_overrides[admin.require_admin] = lambda: {"email": "kevin@example.com"}
    yield TestClient(main.app), db
    main.app.dependency_overrides.clear()


def test_key_routes_need_the_admin_session(api):
    client, _ = api
    main.app.dependency_overrides.pop(admin.require_admin)
    assert client.get("/api/admin/keys").status_code == 401
    assert client.post("/api/admin/keys", json={"label": "x", "scopes": ["orders:place"]}).status_code == 401


def test_create_route_shows_the_key_once_and_lists_never_do(api):
    client, db = api
    r = client.post("/api/admin/keys", json={"label": "mac scripts", "scopes": ["orders:place"]})
    assert r.status_code == 201
    body = r.json()
    assert body["key"].startswith("thk_") and "key_hash" not in body
    listed = client.get("/api/admin/keys").json()["keys"]
    assert len(listed) == 1 and "key" not in listed[0] and "key_hash" not in listed[0]
    assert listed[0]["label"] == "mac scripts" and listed[0]["revoked_at"] is None


def test_create_route_rejects_a_wildcard_scope(api):
    client, _ = api
    r = client.post("/api/admin/keys", json={"label": "x", "scopes": ["*"]})
    assert r.status_code == 422


def test_revoke_and_events_routes(api):
    client, _ = api
    key_id = client.post("/api/admin/keys", json={"label": "ci", "scopes": ["orders:read"]}).json()["id"]
    assert client.post(f"/api/admin/keys/{key_id}/revoke").status_code == 200
    events = client.get(f"/api/admin/keys/{key_id}/events").json()["events"]
    assert {e["outcome"] for e in events} == {"created", "revoked"}
    assert client.post("/api/admin/keys/999/revoke").status_code == 404
    assert client.get("/api/admin/keys/999/events").status_code == 404
