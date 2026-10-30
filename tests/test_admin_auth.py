from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tradehub.api import main
from tradehub.api.dependencies import get_supabase


def supa_for(email=None, error=None):
    def get_user(token):
        if error:
            raise error
        assert token == "jwt"
        return SimpleNamespace(user=SimpleNamespace(email=email))
    return SimpleNamespace(auth=SimpleNamespace(get_user=get_user))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TRADEHUB_ADMIN_EMAIL", "Kevin@Example.com")

    def make(supa):
        main.app.dependency_overrides[get_supabase] = lambda: supa
        return TestClient(main.app)
    yield make
    main.app.dependency_overrides.clear()


AUTH = {"Authorization": "Bearer jwt"}


def test_no_header_is_401(client):
    assert client(supa_for("kevin@example.com")).get("/api/admin/me").status_code == 401


def test_bad_token_is_401(client):
    assert client(supa_for(error=RuntimeError("expired"))).get("/api/admin/me", headers=AUTH).status_code == 401


def test_other_user_is_401(client):
    assert client(supa_for("someone@else.com")).get("/api/admin/me", headers=AUTH).status_code == 401


def test_unset_admin_email_fails_closed(client, monkeypatch):
    monkeypatch.delenv("TRADEHUB_ADMIN_EMAIL")
    assert client(supa_for("kevin@example.com")).get("/api/admin/me", headers=AUTH).status_code == 401


def test_admin_is_200_case_insensitive(client):
    r = client(supa_for("kevin@example.com")).get("/api/admin/me", headers=AUTH)
    assert r.status_code == 200 and r.json() == {"email": "kevin@example.com"}
