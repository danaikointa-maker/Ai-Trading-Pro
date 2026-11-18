"""Broker record lifecycle tests: encrypted replacement and scoped, stale-safe deletion."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.persistence.db import Database
from services.api_gateway.accounts import (
    add_team_member,
    assign_broker_account,
    create_team,
)
from services.api_gateway.auth import create_token
from services.api_gateway.credential_vault import CredentialVault
from services.api_gateway.routes.broker_accounts import router
from services.api_gateway.tenants import create_tenant
from services.api_gateway.users import create_user


@pytest.fixture
def management(tmp_path, settings, monkeypatch):
    monkeypatch.setenv("NO7_CREDENTIAL_VAULT_KEY", CredentialVault.generate_key())
    db = Database(tmp_path / "manage.sqlite3", workspace_id=settings.security.get("workspace_id", "local"))
    tenant = create_tenant(db, "Manage", "manage-admin@example.com", "tenant-password1", "root@example.com")["tenant"]["id"]
    other = create_tenant(db, "Other", "other-admin@example.com", "tenant-password1", "root@example.com")["tenant"]["id"]
    users = {}
    headers = {}
    for key, role, tenant_id in [("owner", "trader", tenant), ("stranger", "trader", tenant),
                                 ("viewer", "viewer", tenant), ("foreign", "admin", other)]:
        users[key] = create_user(db, f"{key}-manage@example.com", "password12345", role, tenant_id)
        token, _ = create_token(settings, users[key]["email"], role)
        headers[key] = {"Authorization": f"Bearer {token}"}
    app = FastAPI()
    app.state.runtime = SimpleNamespace(db=db)
    app.include_router(router)
    with TestClient(app) as client:
        created = client.post("/api/broker-accounts", headers=headers["owner"], json={
            "provider": "mt5", "label": "My Demo", "server": "Broker-Demo", "account_type": "demo",
            "login": "12345678", "password": "fixture-broker-secret", "terminal_path": "old.exe"})
        assert created.status_code == 200
        yield client, db, users, headers, created.json()
    db.close()


def test_edit_retains_or_rotates_encrypted_credentials_and_rejects_stale_writes(management):
    client, db, _users, headers, account = management
    url = f'/api/broker-accounts/{account["id"]}'
    original = db.query_one("SELECT * FROM broker_accounts WHERE id=?", (account["id"],))
    renamed = client.put(url, headers=headers["owner"], json={"expected_updated_at": account["updated_at"], "label": "Renamed"})
    assert renamed.status_code == 200
    assert renamed.json()["label"] == "Renamed"
    assert db.query_one("SELECT credentials_ciphertext FROM broker_accounts WHERE id=?", (account["id"],))[0] == original["credentials_ciphertext"]
    assert client.put(url, headers=headers["owner"], json={"expected_updated_at": account["updated_at"], "label": "Stale"}).status_code == 409
    assert client.delete(url, headers=headers["owner"], params={"expected_updated_at": account["updated_at"]}).status_code == 409
    db.execute("UPDATE broker_accounts SET connection_status='ready_read_only' WHERE id=?", (account["id"],))
    updated = client.put(url, headers=headers["owner"], json={"expected_updated_at": renamed.json()["updated_at"],
                         "login": "87654321", "password": "replacement-secret", "server": "Another-Demo"})
    assert updated.status_code == 200
    assert updated.json()["connection_status"] == "pending_validation"
    assert updated.json()["execution_enabled"] is False
    assert "87654321" not in updated.text and "replacement-secret" not in updated.text
    row = db.query_one("SELECT * FROM broker_accounts WHERE id=?", (account["id"],))
    assert CredentialVault().decrypt(account["id"], row["credentials_ciphertext"]) == {"login": "87654321", "password": "replacement-secret"}
    audit = " ".join(r["detail"] for r in db.query("SELECT detail FROM audit"))
    assert "replacement-secret" not in audit and "87654321" not in audit
    removed = client.delete(url, headers=headers["owner"], params={"expected_updated_at": updated.json()["updated_at"]})
    assert removed.status_code == 200 and removed.json()["orders_sent"] is False
    assert db.query_one("SELECT * FROM broker_accounts WHERE id=?", (account["id"],)) is None


@pytest.mark.parametrize("actor,status", [("stranger", 404), ("foreign", 404), ("viewer", 403)])
def test_other_users_cannot_edit_or_delete(management, actor, status):
    client, db, _users, headers, account = management
    url = f'/api/broker-accounts/{account["id"]}'
    assert client.put(url, headers=headers[actor], json={"expected_updated_at": account["updated_at"], "label": "Denied"}).status_code == status
    assert client.delete(url, headers=headers[actor], params={"expected_updated_at": account["updated_at"]}).status_code == status
    assert db.query_one("SELECT label FROM broker_accounts WHERE id=?", (account["id"],))[0] == "My Demo"


def test_assigned_and_execution_accounts_require_return_or_stop_first(management):
    client, db, users, headers, account = management
    tenant = users["owner"]["tenant_id"]
    team = create_team(db, tenant, "Trading", users["owner"]["email"])
    add_team_member(db, tenant, team["id"], users["stranger"]["email"], "manager")
    assigned = assign_broker_account(db, tenant, account["id"], team["id"], users["stranger"]["email"], users["owner"], 0)
    assert assigned["can_manage"] is False
    url = f'/api/broker-accounts/{account["id"]}'
    assert client.put(url, headers=headers["owner"], json={"expected_updated_at": assigned["updated_at"], "label": "Denied"}).status_code == 409
    assert client.delete(url, headers=headers["owner"], params={"expected_updated_at": assigned["updated_at"]}).status_code == 409
    db.execute("UPDATE broker_accounts SET assignment_team_id=NULL,assignment_manager_email=NULL,execution_enabled=1 WHERE id=?", (account["id"],))
    assert client.delete(url, headers=headers["owner"], params={"expected_updated_at": assigned["updated_at"]}).status_code == 409


def test_duplicate_identity_is_atomic_and_live_stays_disabled(management):
    client, db, _users, headers, _account = management
    second = client.post("/api/broker-accounts", headers=headers["owner"], json={"provider": "mt5",
        "label": "Second", "server": "Broker-Demo", "account_type": "demo", "login": "22222222", "password": "other-secret"}).json()
    url = f'/api/broker-accounts/{second["id"]}'
    assert client.put(url, headers=headers["owner"], json={"expected_updated_at": second["updated_at"], "login": "12345678"}).status_code == 409
    assert db.query_one("SELECT masked_login FROM broker_accounts WHERE id=?", (second["id"],))[0] == second["login"]
    live = client.put(url, headers=headers["owner"], json={"expected_updated_at": second["updated_at"], "account_type": "live"})
    assert live.status_code == 200 and live.json()["connection_status"] == "live_disabled"
    assert live.json()["can_trade"] is False


def test_admin_can_manage_without_reading_credentials_and_vault_failure_preserves_record(management, settings, monkeypatch):
    client, _db, _users, _headers, account = management
    token, _ = create_token(settings, "manage-admin@example.com", "admin")
    headers = {"Authorization": f"Bearer {token}"}
    url = f'/api/broker-accounts/{account["id"]}'
    monkeypatch.delenv("NO7_CREDENTIAL_VAULT_KEY")
    assert client.get(url, headers=headers).json()["can_manage"] is True
    renamed = client.put(url, headers=headers, json={"expected_updated_at": account["updated_at"], "label": "Admin rename"})
    assert renamed.status_code == 200
    assert client.put(url, headers=headers, json={"expected_updated_at": renamed.json()["updated_at"], "password": "new-secret"}).status_code == 503
    assert client.get(url, headers=headers).json()["updated_at"] == renamed.json()["updated_at"]
    assert client.delete(url, headers=headers, params={"expected_updated_at": renamed.json()["updated_at"]}).status_code == 200
