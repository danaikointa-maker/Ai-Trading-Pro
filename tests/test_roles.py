"""Roles: viewer reads, trader acts, admin manages people.

Before this, every authenticated account could do everything — place orders, hit the
kill switch, retrain models, and there was no way to create, demote or disable anyone.
These tests pin the matrix and the two properties that are easy to lose:

* authority comes from the database row, not from the token, so demoting or
  disabling someone takes effect on their next request; and
* you cannot lock yourself out by removing the last active admin.
"""
from __future__ import annotations

import time

import pytest

from packages.persistence.db import Database
from services.api_gateway.auth import hash_password
from services.api_gateway.roles import ADMIN, TRADER, VIEWER, at_least, normalize_role
from services.api_gateway.users import (UserError, active_admins, create_user, delete_user,
                                        get_user, list_users, update_user)


# ------------------------------------------------------------------ pure rules
def test_unknown_roles_fail_closed():
    for junk in (None, "", "root", "superuser", "  ADMINISTRATOR ", "demo?", 42):
        assert normalize_role(junk) == VIEWER, junk
    assert normalize_role("owner") == ADMIN       # legacy demo role
    assert normalize_role("Trader") == TRADER
    assert normalize_role("admin") == ADMIN


def test_role_ranking():
    assert at_least(ADMIN, TRADER) and at_least(ADMIN, VIEWER)
    assert at_least(TRADER, VIEWER) and not at_least(TRADER, ADMIN)
    assert not at_least(VIEWER, TRADER)
    # an unknown role degrades to viewer: it may read, it may not act
    assert at_least("garbage", VIEWER) and not at_least("garbage", TRADER)


# ------------------------------------------------------------------ user store
@pytest.fixture()
def userdb(tmp_path):
    db = Database(str(tmp_path / "users.sqlite3"))
    db.execute("INSERT INTO users(email, password_hash, role, created_at, active) "
               "VALUES(?,?,?,?,1)", ("boss@no7.ai", hash_password("supersecret1"), ADMIN, time.time()))
    yield db
    db.close()


def test_create_validates_email_password_and_role(userdb):
    with pytest.raises(UserError, match="valid email"):
        create_user(userdb, "nope", "longenough1")
    with pytest.raises(UserError, match="at least 8"):
        create_user(userdb, "v@no7.ai", "short")
    with pytest.raises(UserError, match="unknown role"):
        create_user(userdb, "v@no7.ai", "longenough1", role="wizard")
    created = create_user(userdb, "v@no7.ai", "longenough1", role=VIEWER)
    assert created["role"] == VIEWER and created["active"] is True
    with pytest.raises(UserError, match="already exists"):
        create_user(userdb, "V@no7.ai", "longenough1")


def test_password_is_never_stored_in_the_clear(userdb):
    create_user(userdb, "v@no7.ai", "plaintext-secret", role=VIEWER)
    row = userdb.query_one("SELECT password_hash FROM users WHERE email = ?", ("v@no7.ai",))
    assert "plaintext-secret" not in row["password_hash"]
    assert row["password_hash"].startswith("pbkdf2_sha256$")


def test_the_last_active_admin_cannot_be_demoted_or_removed(userdb):
    assert active_admins(userdb) == 1
    with pytest.raises(UserError, match="last active admin"):
        update_user(userdb, "boss@no7.ai", role=TRADER)
    with pytest.raises(UserError, match="last active admin"):
        update_user(userdb, "boss@no7.ai", active=False)
    with pytest.raises(UserError, match="last active admin"):
        delete_user(userdb, "boss@no7.ai")

    # once there is a second admin, the first may step down
    create_user(userdb, "boss2@no7.ai", "supersecret2", role=ADMIN)
    assert update_user(userdb, "boss@no7.ai", role=TRADER)["role"] == TRADER
    assert active_admins(userdb) == 1


def test_users_can_be_disabled_re_enabled_and_listed(userdb):
    create_user(userdb, "t@no7.ai", "longenough1", role=TRADER)
    assert get_user(userdb, "t@no7.ai")["active"] is True
    assert update_user(userdb, "t@no7.ai", active=False)["active"] is False
    assert [u["email"] for u in list_users(userdb)] == ["boss@no7.ai", "t@no7.ai"]
    assert update_user(userdb, "t@no7.ai", active=True)["active"] is True
    with pytest.raises(UserError, match="does not exist"):
        update_user(userdb, "ghost@no7.ai", active=False)


# ----------------------------------------------------------------- http matrix
@pytest.fixture()
def h(token):
    return {"Authorization": f"Bearer {token}"}


def _make_user(client, h, email: str, role: str, password: str = "longenough1") -> str:
    created = client.post("/api/users", json={"email": email, "password": password, "role": role},
                          headers=h)
    assert created.status_code == 200, created.text
    login = client.post("/api/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()["token"]


def _cleanup(client, h, email: str) -> None:
    client.delete(f"/api/users/{email}", headers=h)


def test_admin_can_list_and_create_users(client, h):
    listed = client.get("/api/users", headers=h)
    assert listed.status_code == 200
    body = listed.json()
    assert any(u["email"] == "demo@no7.ai" and u["role"] == ADMIN for u in body["users"])
    assert {r["role"] for r in body["roles"]} == {ADMIN, TRADER, VIEWER}
    # the password hash must never leave the API
    assert "pbkdf2_sha256" not in listed.text

    viewer_token = _make_user(client, h, "viewer@no7.ai", VIEWER)
    try:
        me = client.get("/api/users/me/permissions",
                        headers={"Authorization": f"Bearer {viewer_token}"}).json()
        assert me["role"] == VIEWER
        assert me["can_trade"] is False and me["can_manage_users"] is False
    finally:
        _cleanup(client, h, "viewer@no7.ai")


def test_viewer_can_read_but_not_act(client, h):
    viewer_token = _make_user(client, h, "viewer2@no7.ai", VIEWER)
    vh = {"Authorization": f"Bearer {viewer_token}"}
    try:
        assert client.get("/api/trading/live", headers=vh).status_code == 200
        assert client.get("/api/system/health").status_code == 200

        for method, path, payload in (
            ("post", "/api/system/symbol", {"symbol": "XAUUSD"}),
            ("post", "/api/backtests", {"symbol": "XAUUSD", "bars": 3000}),
            ("post", "/api/forecast/train", {}),
            ("post", "/api/risk/kill-switch", {"reason": "test"}),
        ):
            res = getattr(client, method)(path, json=payload, headers=vh)
            assert res.status_code == 403, f"{method} {path} -> {res.status_code}"
            assert "read-only" in res.json()["detail"]

        # and user management is closed to them twice over
        assert client.get("/api/users", headers=vh).status_code == 403
        assert client.post("/api/users", json={"email": "x@no7.ai", "password": "longenough1"},
                           headers=vh).status_code == 403
    finally:
        _cleanup(client, h, "viewer2@no7.ai")


def test_trader_can_act_but_cannot_manage_users(client, h):
    trader_token = _make_user(client, h, "trader@no7.ai", TRADER)
    th = {"Authorization": f"Bearer {trader_token}"}
    try:
        assert client.get("/api/users", headers=th).status_code == 403
        # a mutating call is permitted (the payload may still be rejected on merits)
        res = client.post("/api/system/symbol", json={"symbol": "XAUUSD"}, headers=th)
        assert res.status_code == 200, res.text
    finally:
        _cleanup(client, h, "trader@no7.ai")


def test_disabling_an_account_takes_effect_immediately(client, h):
    victim = _make_user(client, h, "victim@no7.ai", TRADER)
    vh = {"Authorization": f"Bearer {victim}"}
    try:
        assert client.get("/api/trading/live", headers=vh).status_code == 200
        patched = client.patch("/api/users/victim@no7.ai", json={"active": False}, headers=h)
        assert patched.status_code == 200 and patched.json()["active"] is False

        # same token, one request later: refused, without waiting for expiry
        res = client.get("/api/trading/live", headers=vh)
        assert res.status_code == 403
        assert "disabled" in res.json()["detail"]

        relogin = client.post("/api/auth/login",
                              json={"email": "victim@no7.ai", "password": "longenough1"})
        assert relogin.status_code == 401
    finally:
        _cleanup(client, h, "victim@no7.ai")


def test_role_changes_apply_to_the_existing_token(client, h):
    """The token still says 'trader'; the database now says viewer. The database wins."""
    promoted = _make_user(client, h, "shift@no7.ai", TRADER)
    sh = {"Authorization": f"Bearer {promoted}"}
    try:
        assert client.post("/api/system/symbol", json={"symbol": "XAUUSD"},
                           headers=sh).status_code == 200
        client.patch("/api/users/shift@no7.ai", json={"role": VIEWER}, headers=h)
        res = client.post("/api/system/symbol", json={"symbol": "XAUUSD"}, headers=sh)
        assert res.status_code == 403
        assert client.get("/api/users/me/permissions", headers=sh).json()["role"] == VIEWER
    finally:
        _cleanup(client, h, "shift@no7.ai")


def test_admin_cannot_delete_themselves(client, h):
    res = client.delete("/api/users/demo@no7.ai", headers=h)
    assert res.status_code == 400
    assert "signed in as" in res.json()["detail"]


def test_user_changes_are_audited(client, h):
    _make_user(client, h, "audited@no7.ai", VIEWER)
    try:
        client.patch("/api/users/audited@no7.ai", json={"role": TRADER}, headers=h)
        rows = client.get("/api/system/audit?limit=50", headers=h).json()["audit"]
        actions = [(r["action"], r["actor"]) for r in rows]
        assert any(action == "users.create" and actor == "demo@no7.ai" for action, actor in actions)
        assert any(action == "users.update" for action, _ in actions)
    finally:
        _cleanup(client, h, "audited@no7.ai")
