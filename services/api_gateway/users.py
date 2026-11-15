"""User records: create, change role, disable, delete — with the lockout guard.

Two failure modes this module exists to prevent:

* being left with **no active admin**, which is an unrecoverable lockout (nobody can
  ever manage users again), and
* a role that is not one of the three canonical values slipping into the database and
  later being interpreted as "probably fine".

Every mutation is validated, then audited by the caller so the trail says who did it.
"""
from __future__ import annotations

import re
import time
from typing import Any

from packages.persistence.db import Database
from services.api_gateway.auth import hash_password
from services.api_gateway.roles import ADMIN, VIEWER, normalize_role

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
MIN_PASSWORD = 8
DEFAULT_TENANT_ID = "default"


class UserError(ValueError):
    """A user request that cannot be honoured; the message is shown to the operator."""


def _norm_email(email: str) -> str:
    value = str(email or "").strip().lower()
    if not EMAIL_RE.match(value):
        raise UserError(f"'{email}' is not a valid email address")
    return value


def _check_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise UserError(f"password must be at least {MIN_PASSWORD} characters")
    return password


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "email": row["email"],
        "role": normalize_role(row["role"]),
        "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else DEFAULT_TENANT_ID,
        "active": bool(row["active"] if row["active"] is not None else 1),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"] if "last_login_at" in row.keys() else None,
    }


def list_users(db: Database, tenant_id: str = DEFAULT_TENANT_ID) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM users WHERE tenant_id = ? ORDER BY created_at, email", (tenant_id,))
    return [_row_to_dict(row) for row in rows]


def get_user(db: Database, email: str, tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM users WHERE email = ? AND tenant_id = ?",
                       (str(email).strip().lower(), tenant_id))
    return _row_to_dict(row) if row else None


def active_admins(db: Database, tenant_id: str = DEFAULT_TENANT_ID) -> int:
    rows = db.query("SELECT role, active FROM users WHERE tenant_id = ?", (tenant_id,))
    return sum(1 for row in rows
               if normalize_role(row["role"]) == ADMIN
               and bool(row["active"] if row["active"] is not None else 1))


def create_user(db: Database, email: str, password: str, role: str = VIEWER,
                tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any]:
    email = _norm_email(email)
    password = _check_password(password)
    if not db.query_one("SELECT id FROM tenants WHERE id = ? AND status = 'active'", (tenant_id,)):
        raise UserError("tenant does not exist or is inactive")
    canonical = normalize_role(role)
    if canonical != str(role).strip().lower():
        raise UserError(f"unknown role '{role}' (use admin, trader or viewer)")
    if db.query_one("SELECT email FROM users WHERE email = ?", (email,)):
        raise UserError(f"{email} already exists")
    db.execute("INSERT INTO users(email, password_hash, role, created_at, active, tenant_id) "
               "VALUES(?,?,?,?,1,?)", (email, hash_password(password), canonical, time.time(), tenant_id))
    return get_user(db, email, tenant_id) or {}


def update_user(db: Database, email: str, role: str | None = None,
                active: bool | None = None, password: str | None = None,
                tenant_id: str = DEFAULT_TENANT_ID) -> dict[str, Any]:
    email = str(email).strip().lower()
    current = get_user(db, email, tenant_id)
    if current is None:
        raise UserError(f"{email} does not exist")

    new_role = current["role"]
    if role is not None:
        if normalize_role(role) != str(role).strip().lower():
            raise UserError(f"unknown role '{role}' (use admin, trader or viewer)")
        new_role = normalize_role(role)

    new_active = current["active"] if active is None else bool(active)

    # Lockout guard: the change may not remove the last active admin.
    was_admin = current["role"] == ADMIN and current["active"]
    still_admin = new_role == ADMIN and new_active
    if was_admin and not still_admin and active_admins(db, tenant_id) <= 1:
        raise UserError("this is the last active admin — promote someone else first "
                        "(otherwise nobody can manage users again)")

    if password is not None:
        _check_password(password)

    if new_role != current["role"]:
        db.execute("UPDATE users SET role = ? WHERE email = ? AND tenant_id = ?",
                   (new_role, email, tenant_id))
    if new_active != current["active"]:
        db.execute("UPDATE users SET active = ? WHERE email = ? AND tenant_id = ?",
                   (1 if new_active else 0, email, tenant_id))
    if password is not None:
        db.execute("UPDATE users SET password_hash = ? WHERE email = ? AND tenant_id = ?",
                   (hash_password(password), email, tenant_id))
    return get_user(db, email, tenant_id) or {}


def delete_user(db: Database, email: str, tenant_id: str = DEFAULT_TENANT_ID) -> None:
    email = str(email).strip().lower()
    current = get_user(db, email, tenant_id)
    if current is None:
        raise UserError(f"{email} does not exist")
    if current["role"] == ADMIN and current["active"] and active_admins(db, tenant_id) <= 1:
        raise UserError("this is the last active admin — deactivate it or promote another first")
    db.execute("DELETE FROM users WHERE email = ? AND tenant_id = ?", (email, tenant_id))
