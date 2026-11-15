from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from packages.persistence.db import Database
from services.api_gateway.auth import authenticate, create_token
from services.api_gateway.deps import current_user
from services.api_gateway.platform_admin import create_platform_super_admin
from services.api_gateway.roles import ADMIN
from services.api_gateway.tenants import TenantError, create_tenant, list_tenants
from services.api_gateway.users import list_users
from services.api_gateway.routes.ws import _authority
from services.api_gateway.routes.users import router as users_router
from services.api_gateway.routes.platform import router as platform_router


def test_tenant_creation_scopes_its_first_admin(tmp_path):
    db = Database(tmp_path / "tenant.sqlite3")
    try:
        created = create_tenant(db, "  Broker Team  ", "admin@example.com", "longpassword1", "root@example.com")
        tenant_id = created["tenant"]["id"]

        assert created["tenant"]["name"] == "Broker Team"
        assert created["admin"] == {
            "email": "admin@example.com", "role": "admin", "tenant_id": tenant_id, "active": True
        }
        assert [user["email"] for user in list_users(db, tenant_id)] == ["admin@example.com"]
        assert list_users(db, "default") == []
        assert {tenant["id"] for tenant in list_tenants(db)} == {"default", tenant_id}
    finally:
        db.close()


def test_tenant_and_admin_creation_is_atomic_on_duplicate_email(tmp_path):
    db = Database(tmp_path / "tenant.sqlite3")
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO users(email, password_hash, role, created_at, tenant_id) "
                        "VALUES(?,?,?,?,?)",
                        ("existing@example.com", "hash", "admin", 1.0, "default"))

        before = len(list_tenants(db))
        try:
            create_tenant(db, "No orphan", "existing@example.com", "longpassword1", "root@example.com")
        except TenantError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("duplicate admin email must reject tenant creation")

        assert len(list_tenants(db)) == before
    finally:
        db.close()


def test_platform_admin_is_control_plane_only(settings, monkeypatch, tmp_path):
    from services.api_gateway import deps

    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    db = Database(tmp_path / "platform.sqlite3",
                  workspace_id=settings.security.get("workspace_id", "local"))
    try:
        create_platform_super_admin(db, "root@example.com", "platform-password1")
        try:
            create_platform_super_admin(db, "second-root@example.com", "platform-password1")
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("bootstrap must not silently add another platform super-admin")
        login = authenticate(db, settings, "root@example.com", "platform-password1")
        assert login["user"]["tenant_id"] is None
        assert login["user"]["platform_role"] == "super_admin"
        token, _ = create_token(settings, "root@example.com", "viewer")
        app = FastAPI()
        app.state.runtime = SimpleNamespace(db=db)

        @app.post("/api/platform/tenants")
        def platform_action(user=Depends(current_user)):
            return {"actor": user["email"]}

        @app.get("/api/trading/live")
        def trading_data(user=Depends(current_user)):
            return {"actor": user["email"]}

        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            assert client.post("/api/platform/tenants", headers=headers).status_code == 200
            assert client.get("/api/trading/live", headers=headers).status_code == 403

        authority, code = _authority(SimpleNamespace(db=db), settings, token)
        assert authority is None and code == 4403
    finally:
        db.close()


def test_new_tenant_admin_is_blocked_from_shared_runtime(settings, monkeypatch, tmp_path):
    from services.api_gateway import deps

    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    db = Database(tmp_path / "tenant-runtime.sqlite3",
                  workspace_id=settings.security.get("workspace_id", "local"))
    try:
        created = create_tenant(db, "New tenant", "tenant-admin@example.com",
                                "tenant-password1", "root@example.com")
        token, _ = create_token(settings, "tenant-admin@example.com", "admin")
        app = FastAPI()
        app.state.runtime = SimpleNamespace(db=db)

        @app.get("/api/users")
        def tenant_users(user=Depends(current_user)):
            return {"tenant_id": user["tenant_id"]}

        @app.get("/api/trading/live")
        def trading_data(user=Depends(current_user)):
            return {"actor": user["email"]}

        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            response = client.get("/api/users", headers=headers)
            assert response.status_code == 200
            assert response.json()["tenant_id"] == created["tenant"]["id"]
            assert client.get("/api/trading/live", headers=headers).status_code == 403

        authority, code = _authority(SimpleNamespace(db=db), settings, token)
        assert authority is None and code == 4403
    finally:
        db.close()


def test_user_management_api_only_lists_and_creates_within_tenant(settings, monkeypatch, tmp_path):
    from services.api_gateway import deps

    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    db = Database(tmp_path / "tenant-users.sqlite3",
                  workspace_id=settings.security.get("workspace_id", "local"))
    with db.cursor() as cur:
        cur.execute("INSERT INTO users(email, password_hash, role, created_at, tenant_id) "
                    "VALUES(?,?,?,?,?)",
                    ("default-admin@example.com", "hash", ADMIN, 1.0, "default"))
    tenant = create_tenant(db, "Scoped tenant", "tenant-admin@example.com",
                           "tenant-password1", "root@example.com")["tenant"]
    default_token, _ = create_token(settings, "default-admin@example.com", ADMIN)
    tenant_token, _ = create_token(settings, "tenant-admin@example.com", ADMIN)

    app = FastAPI()
    app.state.runtime = SimpleNamespace(db=db)
    app.include_router(users_router)
    try:
        with TestClient(app) as client:
            default_headers = {"Authorization": f"Bearer {default_token}"}
            tenant_headers = {"Authorization": f"Bearer {tenant_token}"}

            default_users = client.get("/api/users", headers=default_headers).json()["users"]
            tenant_users = client.get("/api/users", headers=tenant_headers).json()["users"]
            assert [user["email"] for user in default_users] == ["default-admin@example.com"]
            assert [user["email"] for user in tenant_users] == ["tenant-admin@example.com"]

            response = client.post("/api/users", headers=tenant_headers,
                                   json={"email": "member@example.com", "password": "member-password1",
                                         "role": "trader"})
            assert response.status_code == 200, response.text
            assert response.json()["tenant_id"] == tenant["id"]
            assert [user["email"] for user in client.get("/api/users", headers=default_headers)
                    .json()["users"]] == ["default-admin@example.com"]
    finally:
        db.close()


def test_platform_admin_creates_and_suspends_tenant(settings, monkeypatch, tmp_path):
    from services.api_gateway import deps

    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    db = Database(tmp_path / "platform-api.sqlite3",
                  workspace_id=settings.security.get("workspace_id", "local"))
    platform_admin = create_platform_super_admin(db, "platform@example.com", "platform-password1")
    row = db.query_one("SELECT role, tenant_id, platform_role FROM users WHERE email = ?",
                       (platform_admin["email"],))
    assert row["role"] == "viewer" and row["tenant_id"] is None
    assert row["platform_role"] == "super_admin"
    token, _ = create_token(settings, platform_admin["email"], "viewer")
    app = FastAPI()
    app.state.runtime = SimpleNamespace(db=db)
    app.include_router(platform_router)
    app.include_router(users_router)
    try:
        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            created = client.post("/api/platform/tenants", headers=headers, json={
                "name": "Managed customer", "admin_email": "customer-admin@example.com",
                "admin_password": "customer-password1",
            })
            assert created.status_code == 200, created.text
            tenant_id = created.json()["tenant"]["id"]
            customer_token, _ = create_token(settings, "customer-admin@example.com", "admin")
            customer_headers = {"Authorization": f"Bearer {customer_token}"}
            assert client.get("/api/users", headers=customer_headers).status_code == 200

            suspended = client.patch(f"/api/platform/tenants/{tenant_id}", headers=headers,
                                     json={"status": "suspended"})
            assert suspended.status_code == 200
            assert client.get("/api/users", headers=customer_headers).status_code == 403
    finally:
        db.close()