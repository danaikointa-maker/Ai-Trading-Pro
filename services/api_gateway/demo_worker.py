"""Isolated read-only probe for an already logged-in MT5 Demo terminal."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from packages.persistence.db import Database
from services.api_gateway.credential_vault import CredentialVault
from integrations.brokers.mt5_readonly import ProbeError, probe_demo


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
    try:
        row = db.query_one("SELECT * FROM broker_accounts WHERE id = ? AND tenant_id = ?",
                           (account_id, tenant_id))
        if row is None or row["account_type"] != "demo" or row["provider"] != "mt5":
            raise ProbeError("Only a registered MT5 Demo account can be validated")
        terminal_path = Path(row["terminal_path"])
        if (terminal_path.name.lower() != "terminal64.exe" or not terminal_path.is_file()
                or not terminal_is_running(terminal_path)):
            raise ProbeError("Open and log in to the specified MT5 terminal first")

        credentials = CredentialVault().decrypt(account_id, row["credentials_ciphertext"])
        if not credentials["login"].isdigit():
            raise ProbeError("Stored MT5 login is not numeric")
        try:
            import MetaTrader5 as terminal
        except ImportError as exc:
            raise ProbeError("Install requirements-mt5.txt in this environment") from exc

        result = probe_demo(terminal, str(terminal_path), int(credentials["login"]),
                            row["server"], row["validation_symbol"])
        db.execute("UPDATE broker_accounts SET connection_status = 'ready_read_only', updated_at = ? "
                   "WHERE id = ? AND tenant_id = ? AND account_type = 'demo'",
                   (time.time(), account_id, tenant_id))
        result.update({"account_id": account_id, "connection_status": "ready_read_only",
                       "execution_enabled": False})
        return result
    except Exception:
        db.execute("UPDATE broker_accounts SET connection_status = 'validation_failed', updated_at = ? "
                   "WHERE id = ? AND tenant_id = ? AND account_type = 'demo'",
                   (time.time(), account_id, tenant_id))
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