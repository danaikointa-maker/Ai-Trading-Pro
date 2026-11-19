"""Isolated read-only probe for an already logged-in MT5 Demo terminal."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from integrations.brokers.mt5_readonly import ProbeError, probe_demo
from integrations.brokers.terminal_locator import (
    TerminalDiscoveryError,
    resolve_running_terminal,
)
from packages.persistence.db import Database
from services.api_gateway.credential_vault import CredentialVault


def terminal_is_running(terminal_path: Path) -> bool:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return False
    env = os.environ.copy()
    env["NO7_EXPECTED_MT5_TERMINAL"] = str(terminal_path)
    check = ("$p = Get-Process terminal64 -ErrorAction SilentlyContinue | "
             "Where-Object { $_.Path -eq $env:NO7_EXPECTED_MT5_TERMINAL }; "
             "if ($p) { exit 0 } else { exit 1 }")
    try:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", check],
                                env=env, capture_output=True, timeout=5, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def validate(database: Path, workspace_id: str, tenant_id: str,
             account_id: str) -> dict:
    if sys.platform != "win32":
        raise ProbeError("MT5 validation requires the Windows host that owns the terminal")
    db = Database(database, workspace_id=workspace_id)
    row = None
    try:
        row = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                           (account_id, tenant_id))
        if row is None or row["account_type"] != "demo" or row["provider"] != "mt5":
            raise ProbeError("Only a registered MT5 Demo account can be validated")
        try:
            terminal_path = resolve_running_terminal()
        except TerminalDiscoveryError as exc:
            raise ProbeError(str(exc)) from exc

        credentials = CredentialVault().decrypt(account_id, row["credentials_ciphertext"])
        if not credentials["login"].isdigit():
            raise ProbeError("Stored MT5 login is not numeric")
        try:
            import MetaTrader5 as terminal
        except ImportError as exc:
            raise ProbeError("Install requirements-mt5.txt in this environment") from exc

        result = probe_demo(terminal, str(terminal_path), int(credentials["login"]),
                            row["server"], row["validation_symbol"])
        updated = db.execute("UPDATE broker_accounts SET connection_status = 'ready_read_only', updated_at = ? "
                             "WHERE id = ? AND tenant_id = ? AND account_type = 'demo' AND updated_at = ?",
                             (time.time(), account_id, tenant_id, row["updated_at"]))
        if updated != 1:
            raise ProbeError("Account changed during validation; refresh and validate again")
        result.update({"account_id": account_id, "connection_status": "ready_read_only",
                       "execution_enabled": False})
        return result
    except Exception:
        if row is not None:
            db.execute("UPDATE broker_accounts SET connection_status = 'validation_failed', updated_at = ? "
                       "WHERE id = ? AND tenant_id = ? AND account_type = 'demo' AND updated_at = ?",
                       (time.time(), account_id, tenant_id, row["updated_at"]))
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--workspace-id", required=True)
    args = parser.parse_args()
    try:
        result = validate(args.database, args.workspace_id, args.tenant_id, args.account_id)
    except ProbeError as exc:
        print(f"BLOCKED: {exc}")
        return 1
    except Exception:
        print("BLOCKED: validation failed; credential and terminal details were withheld")
        return 1
    print(json.dumps(result, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
