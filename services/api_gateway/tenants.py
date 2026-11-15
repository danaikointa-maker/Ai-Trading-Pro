"""Tenant control-plane records and their first administrator."""
from __future__ import annotations

import sqlite3
import time
from typing import Any
from uuid import uuid4

from packages.persistence.db import Database
from services.api_gateway.roles import ADMIN
from services.api_gateway.users import UserError, _check_password, _norm_email
from services.api_gateway.auth import hash_password


class TenantError(ValueError):
    """A tenant-management request that cannot be honoured."""


def list_tenants(db: Database) -> list[dict[str, Any]]:
    rows = db.query("SELECT id, name, status, created_at, created_by FROM tenants ORDER BY created_at, id")
    return [dict(row) for row in rows]


def create_tenant(db: Database, name: str, admin_email: str, admin_password: str,
                  created_by: str) -> dict[str, Any]:
    tenant_name = " ".join(str(name or "").split())
    if not 2 <= len(tenant_name) <= 120:
        raise TenantError("tenant name must be between 2 and 120 characters")
    try:
        email = _norm_email(admin_email)
        password = _check_password(admin_password)
    except UserError as exc:
        raise TenantError(str(exc)) from exc

    tenant_id = str(uuid4())
    created_at = time.time()
    try:
        with db.cursor() as cur:
            cur.execute("INSERT INTO tenants(id, name, status, created_at, created_by) VALUES(?,?,?,?,?)",
                        (tenant_id, tenant_name, "active", created_at, str(created_by)))
            cur.execute(
                "INSERT INTO users(email, password_hash, role, created_at, active, tenant_id) "
                "VALUES(?,?,?,?,1,?)",
                (email, hash_password(password), ADMIN, created_at, tenant_id),
            )
    except sqlite3.IntegrityError as exc:
        raise TenantError("tenant administrator email already exists") from exc

    return {
        "tenant": {"id": tenant_id, "name": tenant_name, "status": "active",
                   "created_at": created_at, "created_by": str(created_by)},
        "admin": {"email": email, "role": ADMIN, "tenant_id": tenant_id, "active": True},
    }


def set_tenant_status(db: Database, tenant_id: str, status: str) -> dict[str, Any]:
    if tenant_id == "default":
        raise TenantError("the default workspace tenant cannot be suspended")
    if status not in {"active", "suspended"}:
        raise TenantError("tenant status must be active or suspended")
    changed = db.execute("UPDATE tenants SET status = ? WHERE id = ?", (status, tenant_id))
    if not changed:
        raise TenantError("tenant does not exist")
    row = db.query_one("SELECT id, name, status, created_at, created_by FROM tenants WHERE id = ?",
                       (tenant_id,))
    return dict(row)