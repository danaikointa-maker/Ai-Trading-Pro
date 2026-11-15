import json
import sys
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from packages.persistence.db import Database
from services.api_gateway.accounts import (AccountError, add_team_member, assign_broker_account,
                                           create_broker_account, create_team, get_broker_account,
                                           list_teams, unassign_broker_account)
from services.api_gateway.credential_vault import CredentialVault
from services.api_gateway import demo_validation
from services.api_gateway.demo_validation import validate_demo_account
from services.api_gateway import demo_worker
from services.api_gateway.tenants import create_tenant
from services.api_gateway.users import create_user, get_user
from services.api_gateway.auth import create_token
from services.api_gateway.routes.broker_accounts import router as broker_accounts_router
from integrations.brokers import registry as registry_module


def test_assignment_moves_control_but_owner_keeps_read_only_progress(tmp_path):
    db = Database(tmp_path / "accounts.sqlite3")
    vault = CredentialVault(CredentialVault.generate_key())
    try:
        tenant = create_tenant(db, "Accounts", "tenant-admin@example.com",
                               "tenant-password1", "root@example.com")["tenant"]
        tenant_id = tenant["id"]
        owner = create_user(db, "owner@example.com", "owner-password1", "trader", tenant_id)
        manager = create_user(db, "manager@example.com", "manager-password1", "trader", tenant_id)
        member = create_user(db, "member@example.com", "member-password1", "viewer", tenant_id)
        team = create_team(db, tenant_id, "Demo team", "tenant-admin@example.com")
        add_team_member(db, tenant_id, team["id"], manager["email"], "manager")
        add_team_member(db, tenant_id, team["id"], member["email"], "member")
        assignable_teams = list_teams(db, tenant_id, owner["email"], can_assign=True)
        assert [candidate["id"] for candidate in assignable_teams] == [team["id"]]
        assert [candidate["user_email"] for candidate in assignable_teams[0]["members"]] == [manager["email"]]

        account = create_broker_account(
            db, vault, tenant_id=tenant_id, owner_email=owner["email"], provider="mt5",
            label="Connext Demo 1", server="Connext-Demo", account_type="demo",
            login="12345678", password="broker-secret", created_by=owner["email"],
        )
        assert account["login"] == "****5678"
        assert account["connection_status"] == "pending_validation"
        assert account["execution_enabled"] is False and account["can_trade"] is False
        assert account["can_control"] is True and account["can_assign"] is True

        stored = db.query_one("SELECT credentials_ciphertext FROM broker_accounts WHERE id = ?",
                              (account["id"],))["credentials_ciphertext"]
        assert b"12345678" not in stored and b"broker-secret" not in stored
        assert vault.decrypt(account["id"], stored) == {
            "login": "12345678", "password": "broker-secret"
        }

        assigned = assign_broker_account(db, tenant_id, account["id"], team["id"],
                                         manager["email"], owner, expected_version=0)
        assert assigned["assignment_version"] == 1
        assert assigned["can_control"] is False
        assert get_broker_account(db, tenant_id, account["id"], owner)["can_view"] is True
        assert get_broker_account(db, tenant_id, account["id"], manager)["can_control"] is True
        assert get_broker_account(db, tenant_id, account["id"], manager)["can_trade"] is False
        assert get_broker_account(db, tenant_id, account["id"], member)["can_view"] is True
        assert get_broker_account(db, tenant_id, account["id"], member)["can_control"] is False

        with pytest.raises(AccountError, match="stale assignment version"):
            assign_broker_account(db, tenant_id, account["id"], team["id"],
                                  manager["email"], owner, expected_version=0)

        tenant_admin = get_user(db, "tenant-admin@example.com", tenant_id)
        returned = unassign_broker_account(db, tenant_id, account["id"], tenant_admin,
                                           expected_version=1)
        assert returned["assignment_version"] == 2
        assert get_broker_account(db, tenant_id, account["id"], owner)["can_control"] is True
        history = db.query("SELECT actor, action, detail FROM audit ORDER BY id")
        assert [row["action"] for row in history if row["action"].startswith("broker_account.")] == [
            "broker_account.assign", "broker_account.unassign",
        ]
        assert all(row["actor"] and account["id"] in row["detail"]
                   for row in history if row["action"].startswith("broker_account."))
    finally:
        db.close()


def test_live_and_demo_are_separate_and_live_is_disabled(tmp_path):
    db = Database(tmp_path / "account-types.sqlite3")
    vault = CredentialVault(CredentialVault.generate_key())
    try:
        tenant = create_tenant(db, "Types", "admin-types@example.com",
                               "tenant-password1", "root@example.com")["tenant"]
        owner = create_user(db, "owner-types@example.com", "owner-password1", "trader", tenant["id"])
        demo = create_broker_account(
            db, vault, tenant_id=tenant["id"], owner_email=owner["email"], provider="mt5",
            label="Demo", server="Connext-Demo", account_type="demo", login="1111",
            password="demo-pass", created_by=owner["email"],
        )
        live = create_broker_account(
            db, vault, tenant_id=tenant["id"], owner_email=owner["email"], provider="mt5",
            label="Live", server="Connext-Live", account_type="live", login="2222",
            password="live-pass", created_by=owner["email"],
        )
        assert demo["id"] != live["id"]
        assert demo["account_type"] == "demo" and demo["execution_enabled"] is False
        assert live["account_type"] == "live" and live["connection_status"] == "live_disabled"
        assert live["can_trade"] is False
        with pytest.raises(AccountError, match="limited to Demo"):
            validate_demo_account(db, tenant["id"], live["id"], owner)
    finally:
        db.close()


def test_broker_account_api_redacts_credentials_and_scopes_tenants(settings, monkeypatch, tmp_path):
    from services.api_gateway import deps

    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setenv("NO7_CREDENTIAL_VAULT_KEY", CredentialVault.generate_key())
    db = Database(tmp_path / "account-api.sqlite3",
                  workspace_id=settings.security.get("workspace_id", "local"))
    tenant_a = create_tenant(db, "Tenant A", "admin-a@example.com",
                             "tenant-password1", "root@example.com")["tenant"]
    create_tenant(db, "Tenant B", "admin-b@example.com",
                  "tenant-password1", "root@example.com")
    trader_a = create_user(db, "trader-a@example.com", "trader-password1", "trader", tenant_a["id"])
    token_a, _ = create_token(settings, trader_a["email"], "trader")
    token_b, _ = create_token(settings, "admin-b@example.com", "admin")

    app = FastAPI()
    app.state.runtime = SimpleNamespace(db=db)
    app.include_router(broker_accounts_router)
    try:
        with TestClient(app) as client:
            headers_a = {"Authorization": f"Bearer {token_a}"}
            headers_b = {"Authorization": f"Bearer {token_b}"}
            response = client.post("/api/broker-accounts", headers=headers_a, json={
                "provider": "mt5", "label": "Demo account", "server": "Connext-Demo",
                "account_type": "demo", "login": "987654321", "password": "hidden-broker-password",
            })
            assert response.status_code == 200, response.text
            assert "987654321" not in response.text
            assert "hidden-broker-password" not in response.text
            account_id = response.json()["id"]
            assert response.json()["login"].endswith("4321")
            assert response.json()["tenant_id"] == tenant_a["id"]

            account_list = client.get("/api/broker-accounts", headers=headers_a).json()["accounts"]
            assert [account["id"] for account in account_list] == [account_id]
            other_tenant_list = client.get("/api/broker-accounts", headers=headers_b).json()["accounts"]
            assert other_tenant_list == []

        stored = db.query_one("SELECT credentials_ciphertext FROM broker_accounts WHERE id = ?",
                              (account_id,))["credentials_ciphertext"]
        assert b"987654321" not in stored and b"hidden-broker-password" not in stored
    finally:
        db.close()


def test_broker_registry_never_uses_global_account_credentials(monkeypatch):
    captured = {}

    class FakeBroker:
        def __init__(self, profile, **kwargs):
            captured.update(kwargs)
            self.id = profile["id"]

        def connect(self):
            return False

    monkeypatch.setenv("MT5_LOGIN", "123456")
    monkeypatch.setenv("MT5_PASSWORD", "must-not-be-used")
    monkeypatch.setenv("MT5_SERVER", "Wrong-Server")
    monkeypatch.setattr(registry_module, "MT5Broker", FakeBroker)
    settings = SimpleNamespace(
        brokers={"brokers": [{"id": "account-a", "adapter": "mt5", "server": "Profile-Server"}]},
        default_broker_id=lambda: "account-a",
        app={},
    )
    registry = registry_module.BrokerRegistry(settings, feed=object())
    registry.build()

    assert captured["login"] is None
    assert captured["password"] == ""
    assert captured["server"] == "Profile-Server"


def test_demo_validation_worker_receives_account_id_not_broker_secrets(tmp_path, monkeypatch):
    db = Database(tmp_path / "demo-validation.sqlite3")
    vault_key = CredentialVault.generate_key()
    monkeypatch.setenv("NO7_CREDENTIAL_VAULT_KEY", vault_key)
    vault = CredentialVault(vault_key)
    try:
        tenant = create_tenant(db, "Validation", "validation-admin@example.com",
                               "tenant-password1", "root@example.com")["tenant"]
        owner = create_user(db, "validation-owner@example.com", "owner-password1",
                            "trader", tenant["id"])
        terminal_path = tmp_path / "terminal64.exe"
        terminal_path.write_bytes(b"not executed by the mocked validator")
        account = create_broker_account(
            db, vault, tenant_id=tenant["id"], owner_email=owner["email"], provider="mt5",
            label="Demo", server="Connext-Demo", account_type="demo", login="99887766",
            password="broker-password-not-in-args", created_by=owner["email"],
            terminal_path=str(terminal_path), validation_symbol="XAUUSD",
        )
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["env"] = kwargs["env"]
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "read_only": True, "account_type": "demo", "symbol": "XAUUSD",
                "execution_enabled": False,
            }), "")

        monkeypatch.setattr(demo_validation.subprocess, "run", fake_run)
        result = validate_demo_account(db, tenant["id"], account["id"], owner)

        command = " ".join(captured["command"])
        assert account["id"] in command
        assert "99887766" not in command
        assert "broker-password-not-in-args" not in command
        assert captured["env"]["NO7_CREDENTIAL_VAULT_KEY"] == vault_key
        assert result["read_only"] is True and result["execution_enabled"] is False
    finally:
        db.close()


def test_demo_worker_marks_only_matching_read_only_demo_ready(tmp_path, monkeypatch):
    db_path = tmp_path / "demo-worker.sqlite3"
    db = Database(db_path)
    vault_key = CredentialVault.generate_key()
    vault = CredentialVault(vault_key)
    monkeypatch.setenv("NO7_CREDENTIAL_VAULT_KEY", vault_key)
    terminal_path = tmp_path / "terminal64.exe"
    terminal_path.write_bytes(b"not executed by the fake terminal")
    try:
        tenant = create_tenant(db, "Worker", "worker-admin@example.com",
                               "tenant-password1", "root@example.com")["tenant"]
        owner = create_user(db, "worker-owner@example.com", "owner-password1", "trader", tenant["id"])
        account = create_broker_account(
            db, vault, tenant_id=tenant["id"], owner_email=owner["email"], provider="mt5",
            label="Demo worker", server="Connext-Demo", account_type="demo", login="123456",
            password="broker-password", created_by=owner["email"], terminal_path=str(terminal_path),
        )
    finally:
        db.close()

    class FakeTerminal:
        ACCOUNT_TRADE_MODE_DEMO = 0

        @staticmethod
        def initialize(path, timeout):
            return path == str(terminal_path) and timeout == 5000

        @staticmethod
        def account_info():
            return SimpleNamespace(trade_mode=0, login=123456, server="Connext-Demo",
                                   currency="USD", balance=10000.0, equity=10000.0)

        @staticmethod
        def terminal_info():
            return SimpleNamespace(connected=True)

        @staticmethod
        def symbol_info_tick(symbol):
            return SimpleNamespace(bid=2000.0, ask=2000.1, time=1_700_000_000)

        @staticmethod
        def shutdown():
            return None

    monkeypatch.setattr(demo_worker.sys, "platform", "win32")
    monkeypatch.setattr(demo_worker, "terminal_is_running", lambda path: path == terminal_path)
    monkeypatch.setitem(sys.modules, "MetaTrader5", FakeTerminal)

    result = demo_worker.validate(db_path, "local", tenant["id"], account["id"])
    reopened = Database(db_path)
    try:
        status = reopened.query_one("SELECT connection_status, execution_enabled FROM broker_accounts WHERE id = ?",
                                    (account["id"],))
        assert result["read_only"] is True
        assert result["connection_status"] == "ready_read_only"
        assert result["execution_enabled"] is False
        assert status["connection_status"] == "ready_read_only"
        assert status["execution_enabled"] == 0
    finally:
        reopened.close()