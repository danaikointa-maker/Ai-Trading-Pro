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
        "active": bool(row["active"] if row["active"] is not None else 1),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"] if "last_login_at" in row.keys() else None,
    }


def list_users(db: Database) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM users ORDER BY created_at, email")
    return [_row_to_dict(row) for row in rows]


def get_user(db: Database, email: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM users WHERE email = ?", (str(email).strip().lower(),))
    return _row_to_dict(row) if row else None


def active_admins(db: Database) -> int:
    rows = db.query("SELECT role, active FROM users")
    return sum(1 for row in rows
               if normalize_role(row["role"]) == ADMIN
               and bool(row["active"] if row["active"] is not None else 1))


def create_user(db: Database, email: str, password: str, role: str = VIEWER) -> dict[str, Any]:
    email = _norm_email(email)
    password = _check_password(password)
    canonical = normalize_role(role)
    if canonical != str(role).strip().lower():
        raise UserError(f"unknown role '{role}' (use admin, trader or viewer)")
    if db.query_one("SELECT email FROM users WHERE email = ?", (email,)):
        raise UserError(f"{email} already exists")
    db.execute("INSERT INTO users(email, password_hash, role, created_at, active) "
               "VALUES(?,?,?,?,1)", (email, hash_password(password), canonical, time.time()))
    return get_user(db, email) or {}


def update_user(db: Database, email: str, role: str | None = None,
                active: bool | None = None, password: str | None = None) -> dict[str, Any]:
    email = str(email).strip().lower()
    current = get_user(db, email)
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
    if was_admin and not still_admin and active_admins(db) <= 1:
        raise UserError("this is the last active admin — promote someone else first "
                        "(otherwise nobody can manage users again)")

    if password is not None:
        _check_password(password)

    if new_role != current["role"]:
        db.execute("UPDATE users SET role = ? WHERE email = ?", (new_role, email))
    if new_active != current["active"]:
        db.execute("UPDATE users SET active = ? WHERE email = ?", (1 if new_active else 0, email))
    if password is not None:
        db.execute("UPDATE users SET password_hash = ? WHERE email = ?",
                   (hash_password(password), email))
    return get_user(db, email) or {}


def delete_user(db: Database, email: str) -> None:
    email = str(email).strip().lower()
    current = get_user(db, email)
    if current is None:
        raise UserError(f"{email} does not exist")
    if current["role"] == ADMIN and current["active"] and active_admins(db) <= 1:
        raise UserError("this is the last active admin — deactivate it or promote another first")
    db.execute("DELETE FROM users WHERE email = ?", (email,))
