"""One-shot, isolated read-only Demo terminal validation."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from packages.persistence.db import Database
from services.api_gateway.accounts import AccountError, _account_access


def validate_demo_account(db: Database, tenant_id: str, account_id: str,
                          user: dict[str, Any]) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                       (account_id, tenant_id))
    if row is None:
        raise AccountError("broker account does not exist")
    if not _account_access(db, row, user)["can_control"]:
        raise AccountError("only the current account controller may validate this connection")
    if row["account_type"] != "demo":
        raise AccountError("read-only validation is limited to Demo accounts")
    if row["provider"] != "mt5":
        raise AccountError("this validator supports MT5 accounts only")
    if not row["terminal_path"]:
        raise AccountError("set the MT5 terminal path on this account first")

    command = [
        sys.executable, "-m", "services.api_gateway.demo_worker",
        "--account-id", account_id,
        "--tenant-id", tenant_id,
        "--database", str(db.path),
        "--workspace-id", db.workspace_id,
    ]
    env = os.environ.copy()
    try:
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[2],
                                env=env, capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AccountError("Demo validation timed out; no trade was sent") from exc
    except OSError as exc:
        raise AccountError("Demo validation worker could not start") from exc

    output = result.stdout.strip()
    if result.returncode != 0:
        message = output.removeprefix("BLOCKED: ").strip()
        raise AccountError(message or "Demo validation failed; details were withheld")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise AccountError("Demo validation worker returned an invalid response") from exc


def read_demo_positions(db: Database, tenant_id: str, account_id: str,
                        user: dict[str, Any]) -> dict[str, Any]:
    """Fetch one fresh, read-only snapshot for a previously linked Demo account."""
    row = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                       (account_id, tenant_id))
    if row is None:
        raise AccountError("broker account does not exist")
    if not _account_access(db, row, user)["can_view"]:
        raise AccountError("you are not allowed to view this broker account")
    if (row["provider"] != "mt5" or row["account_type"] != "demo"
            or row["connection_status"] != "ready_read_only"):
        raise AccountError("link and verify this MT5 Demo account as read-only in Brokers first")

    command = [
        sys.executable, "-m", "services.api_gateway.demo_worker",
        "--account-id", account_id,
        "--tenant-id", tenant_id,
        "--database", str(db.path),
        "--workspace-id", db.workspace_id,
        "--positions",
    ]
    env = os.environ.copy()
    try:
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[2],
                                env=env, capture_output=True, text=True, timeout=30, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AccountError("MT5 position read timed out; no trade was sent") from exc
    except OSError as exc:
        raise AccountError("MT5 position reader could not start") from exc

    output = result.stdout.strip()
    if result.returncode != 0:
        message = output.removeprefix("BLOCKED: ").strip()
        raise AccountError(message or "MT5 position read failed; details were withheld")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise AccountError("MT5 position reader returned an invalid response") from exc
    if (not isinstance(payload, dict) or payload.get("account_id") != account_id
            or payload.get("read_only") is not True
            or payload.get("execution_enabled") is not False
            or not isinstance(payload.get("positions"), list)):
        raise AccountError("MT5 position response did not match the linked read-only account")
    for position in payload["positions"]:
        position["broker_id"] = account_id
    return payload
