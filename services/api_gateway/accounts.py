"""Tenant-scoped teams and managed broker-account records."""
from __future__ import annotations

import re
import sqlite3
import time
from typing import Any
from uuid import uuid4

from packages.persistence.db import Database
from services.api_gateway.credential_vault import CredentialVault, mask_login
from services.api_gateway.roles import ADMIN, TRADER

_PROVIDER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class AccountError(ValueError):
    """An account/team request that cannot be honoured."""


def create_team(db: Database, tenant_id: str, name: str, created_by: str) -> dict[str, Any]:
    clean_name = " ".join(str(name or "").split())
    if not 2 <= len(clean_name) <= 80:
        raise AccountError("team name must be between 2 and 80 characters")
    if not db.query_one("SELECT id FROM tenants WHERE id = ? AND status = 'active'", (tenant_id,)):
        raise AccountError("tenant does not exist or is inactive")
    team_id = str(uuid4())
    created_at = time.time()
    try:
        db.execute("INSERT INTO teams(id, tenant_id, name, created_at, created_by) VALUES(?,?,?,?,?)",
                   (team_id, tenant_id, clean_name, created_at, created_by))
    except sqlite3.IntegrityError as exc:
        raise AccountError("team name already exists in this tenant") from exc
    return {"id": team_id, "tenant_id": tenant_id, "name": clean_name, "status": "active",
            "created_at": created_at, "created_by": created_by, "members": []}


def add_team_member(db: Database, tenant_id: str, team_id: str, email: str,
                    team_role: str = "member") -> dict[str, Any]:
    normalized = str(email or "").strip().lower()
    if team_role not in {"manager", "member"}:
        raise AccountError("team role must be manager or member")
    team = db.query_one("SELECT id FROM teams WHERE id = ? AND tenant_id = ? AND status = 'active'",
                        (team_id, tenant_id))
    user = db.query_one("SELECT email, role, active FROM users WHERE email = ? AND tenant_id = ?",
                        (normalized, tenant_id))
    if not team or not user or not bool(user["active"] if user["active"] is not None else 1):
        raise AccountError("active team and tenant user are required")
    if team_role == "manager" and user["role"] != TRADER:
        raise AccountError("an account manager must have the trader role")
    db.execute("INSERT INTO team_members(team_id, user_email, team_role, active, created_at) "
               "VALUES(?,?,?,?,?) ON CONFLICT(team_id, user_email) DO UPDATE SET "
               "team_role=excluded.team_role, active=1",
               (team_id, normalized, team_role, 1, time.time()))
    return {"team_id": team_id, "email": normalized, "team_role": team_role, "active": True}


def remove_team_member(db: Database, tenant_id: str, team_id: str, email: str) -> None:
    normalized = str(email or "").strip().lower()
    if not db.query_one("SELECT id FROM teams WHERE id = ? AND tenant_id = ?", (team_id, tenant_id)):
        raise AccountError("team does not exist")
    assigned = db.query_one("SELECT id FROM broker_accounts WHERE tenant_id = ? "
                            "AND assignment_team_id = ? AND assignment_manager_email = ?",
                            (tenant_id, team_id, normalized))
    if assigned:
        raise AccountError("unassign or reassign this manager's broker accounts first")
    db.execute("UPDATE team_members SET active = 0 WHERE team_id = ? AND user_email = ?",
               (team_id, normalized))


def list_teams(db: Database, tenant_id: str, actor_email: str, is_admin: bool = False,
               can_assign: bool = False) -> list[dict[str, Any]]:
    if is_admin or can_assign:
        teams = db.query("SELECT id, tenant_id, name, status, created_at, created_by FROM teams "
                         "WHERE tenant_id = ? ORDER BY created_at, name", (tenant_id,))
    else:
        teams = db.query("SELECT t.id, t.tenant_id, t.name, t.status, t.created_at, t.created_by "
                         "FROM teams t JOIN team_members m ON m.team_id=t.id "
                         "WHERE t.tenant_id = ? AND m.user_email = ? AND m.active = 1 "
                         "ORDER BY t.created_at, t.name", (tenant_id, actor_email))
    result = []
    for row in teams:
        member_query = "SELECT user_email, team_role FROM team_members WHERE team_id = ? AND active = 1"
        if can_assign and not is_admin:
            member_query += " AND team_role = 'manager'"
        member_query += " ORDER BY user_email"
        members = db.query(member_query, (row["id"],))
        result.append({**dict(row), "members": [dict(member) for member in members]})
    return result


def _account_access(db: Database, row: Any, user: dict[str, Any]) -> dict[str, bool]:
    email = str(user.get("email", "")).lower()
    role = user.get("role")
    is_admin = role == ADMIN
    is_owner = row["owner_email"] == email
    is_manager = row["assignment_manager_email"] == email
    is_team_member = False
    if row["assignment_team_id"]:
        is_team_member = bool(db.query_one(
            "SELECT 1 FROM team_members WHERE team_id = ? AND user_email = ? AND active = 1",
            (row["assignment_team_id"], email)))
    assigned = bool(row["assignment_team_id"] or row["assignment_manager_email"])
    manager_role = False
    if is_manager and row["assignment_team_id"]:
        membership = db.query_one("SELECT team_role FROM team_members "
                                  "WHERE team_id = ? AND user_email = ? AND active = 1",
                                  (row["assignment_team_id"], email))
        manager_role = bool(membership and membership["team_role"] == "manager")
    can_control = (
        (not assigned and is_owner and role in {ADMIN, TRADER})
        or (assigned and is_manager and manager_role and role == TRADER)
    )
    can_view = is_admin or is_owner or is_manager or is_team_member
    can_assign = is_admin or (is_owner and not assigned)
    can_trade = (can_control and row["account_type"] == "demo"
                 and bool(row["execution_enabled"])
                 and row["connection_status"] == "ready")
    return {"can_view": can_view, "can_control": can_control,
            "can_assign": can_assign, "can_trade": can_trade}


def _public_account(db: Database, row: Any, user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "tenant_id": row["tenant_id"], "owner_email": row["owner_email"],
        "provider": row["provider"], "label": row["label"], "server": row["server"],
        "account_type": row["account_type"], "login": row["masked_login"],
        "terminal_path_configured": bool(row["terminal_path"]),
        "connection_status": row["connection_status"],
        "assigned_team_id": row["assignment_team_id"],
        "assigned_manager_email": row["assignment_manager_email"],
        "assignment_version": row["assignment_version"],
        "execution_enabled": bool(row["execution_enabled"]),
        **_account_access(db, row, user),
    }


def create_broker_account(db: Database, vault: CredentialVault, *, tenant_id: str,
                          owner_email: str, provider: str, label: str, server: str,
                          account_type: str, login: str, password: str,
                          created_by: str, terminal_path: str = "",
                          validation_symbol: str = "XAUUSD") -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    clean_label = " ".join(str(label or "").split())
    clean_server = str(server or "").strip()
    normalized_login = str(login or "").strip()
    clean_symbol = str(validation_symbol or "").strip()
    if not _PROVIDER_RE.fullmatch(normalized_provider):
        raise AccountError("provider must be a short identifier")
    if (not 2 <= len(clean_label) <= 100 or not clean_server or not normalized_login
            or not password or not clean_symbol):
        raise AccountError("label, server, broker login, password and validation symbol are required")
    if account_type not in {"demo", "live"}:
        raise AccountError("account type must be demo or live")
    owner = db.query_one("SELECT email, role, active FROM users WHERE email = ? AND tenant_id = ?",
                         (owner_email.lower(), tenant_id))
    if not owner or not bool(owner["active"] if owner["active"] is not None else 1):
        raise AccountError("active owner in this tenant is required")
    if not db.query_one("SELECT id FROM tenants WHERE id = ? AND status = 'active'", (tenant_id,)):
        raise AccountError("tenant does not exist or is inactive")

    account_id = str(uuid4())
    encrypted = vault.encrypt(account_id, normalized_login, password)
    fingerprint = vault.fingerprint(tenant_id, normalized_provider, clean_server, normalized_login)
    timestamp = time.time()
    status = "pending_validation" if account_type == "demo" else "live_disabled"
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO broker_accounts(id, tenant_id, owner_email, provider, label, server, "
                "account_type, terminal_path, validation_symbol, masked_login, login_fingerprint, credentials_ciphertext, "
                "connection_status, created_at, created_by, updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account_id, tenant_id, owner_email.lower(), normalized_provider, clean_label, clean_server,
                 account_type, str(terminal_path or "").strip(), clean_symbol, mask_login(normalized_login),
                 fingerprint, encrypted, status,
                 timestamp, created_by, timestamp),
            )
    except sqlite3.IntegrityError as exc:
        raise AccountError("this broker login is already registered in the tenant") from exc
    row = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?", (account_id, tenant_id))
    return _public_account(db, row, {"email": owner_email.lower(), "role": owner["role"]})


def list_broker_accounts(db: Database, tenant_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
    email = str(user.get("email", "")).lower()
    if user.get("role") == ADMIN:
        rows = db.query("SELECT * FROM broker_accounts WHERE tenant_id = ? ORDER BY created_at, id", (tenant_id,))
    else:
        rows = db.query(
            "SELECT DISTINCT a.* FROM broker_accounts a "
            "LEFT JOIN team_members m ON m.team_id = a.assignment_team_id "
            "AND m.user_email = ? AND m.active = 1 "
            "WHERE a.tenant_id = ? AND (a.owner_email = ? OR a.assignment_manager_email = ? "
            "OR m.user_email IS NOT NULL) ORDER BY a.created_at, a.id",
            (email, tenant_id, email, email),
        )
    return [_public_account(db, row, user) for row in rows]


def get_broker_account(db: Database, tenant_id: str, account_id: str,
                       user: dict[str, Any]) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                       (account_id, tenant_id))
    if row is None:
        return None
    account = _public_account(db, row, user)
    return account if account["can_view"] else None


def assign_broker_account(db: Database, tenant_id: str, account_id: str, team_id: str,
                          manager_email: str, actor: dict[str, Any],
                          expected_version: int) -> dict[str, Any]:
    normalized_manager = manager_email.strip().lower()
    actor_email = str(actor.get("email", "")).lower()
    with db.cursor() as cur:
        row = cur.execute("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                          (account_id, tenant_id)).fetchone()
        if row is None:
            raise AccountError("broker account does not exist")
        if int(row["assignment_version"]) != expected_version:
            raise AccountError("stale assignment version; refresh account state and retry")
        already_assigned = bool(row["assignment_team_id"] or row["assignment_manager_email"])
        if already_assigned and actor.get("role") != ADMIN:
            raise AccountError("only tenant admin may change an existing assignment")
        if not already_assigned and actor.get("role") != ADMIN and row["owner_email"] != actor_email:
            raise AccountError("only the account owner or tenant admin may assign this account")

        team = cur.execute("SELECT id FROM teams WHERE id = ? AND tenant_id = ? AND status = 'active'",
                           (team_id, tenant_id)).fetchone()
        manager = cur.execute("SELECT email, role, active FROM users WHERE email = ? AND tenant_id = ?",
                              (normalized_manager, tenant_id)).fetchone()
        membership = cur.execute("SELECT team_role, active FROM team_members "
                                 "WHERE team_id = ? AND user_email = ?",
                                 (team_id, normalized_manager)).fetchone()
        if (not team or not manager or manager["role"] != TRADER
                or not bool(manager["active"] if manager["active"] is not None else 1)
                or not membership or membership["team_role"] != "manager"
                or not bool(membership["active"])):
            raise AccountError("assigned manager must be an active trader manager in the selected team")

        updated = cur.execute("UPDATE broker_accounts SET assignment_team_id = ?, assignment_manager_email = ?, "
                              "assignment_version = assignment_version + 1, updated_at = ? "
                              "WHERE id = ? AND tenant_id = ? AND assignment_version = ?",
                              (team_id, manager["email"], time.time(), account_id,
                               tenant_id, expected_version))
        if updated.rowcount != 1:
            raise AccountError("stale assignment version; refresh account state and retry")
        db.audit(actor_email, "broker_account.assign", {
            "account_id": account_id, "from_team_id": row["assignment_team_id"],
            "from_manager_email": row["assignment_manager_email"],
            "to_team_id": team_id, "to_manager_email": manager["email"],
            "assignment_version": expected_version + 1,
        })
    refreshed = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                             (account_id, tenant_id))
    return _public_account(db, refreshed, actor)


def unassign_broker_account(db: Database, tenant_id: str, account_id: str,
                            actor: dict[str, Any], expected_version: int) -> dict[str, Any]:
    if actor.get("role") != ADMIN:
        raise AccountError("only tenant admin may return an assigned account to its owner")
    actor_email = str(actor.get("email", "")).lower()
    with db.cursor() as cur:
        row = cur.execute("SELECT assignment_version, assignment_team_id, assignment_manager_email "
                          "FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                          (account_id, tenant_id)).fetchone()
        if row is None:
            raise AccountError("broker account does not exist")
        if int(row["assignment_version"]) != expected_version:
            raise AccountError("stale assignment version; refresh account state and retry")
        if not row["assignment_team_id"] and not row["assignment_manager_email"]:
            raise AccountError("broker account is not assigned")
        updated = cur.execute("UPDATE broker_accounts SET assignment_team_id = NULL, "
                              "assignment_manager_email = NULL, assignment_version = assignment_version + 1, "
                              "updated_at = ? WHERE id = ? AND tenant_id = ? AND assignment_version = ?",
                              (time.time(), account_id, tenant_id, expected_version))
        if updated.rowcount != 1:
            raise AccountError("stale assignment version; refresh account state and retry")
        db.audit(actor_email, "broker_account.unassign", {
            "account_id": account_id, "from_team_id": row["assignment_team_id"],
            "from_manager_email": row["assignment_manager_email"],
            "to_team_id": None, "to_manager_email": None,
            "assignment_version": expected_version + 1,
        })
    refreshed = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                             (account_id, tenant_id))
    return _public_account(db, refreshed, actor)