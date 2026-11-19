"""One-shot, isolated read-only Demo terminal validation."""
from __future__ import annotations

import math
import time
from typing import Any

from packages.persistence.db import Database
from services.api_gateway.accounts import AccountError, _account_access
from services.api_gateway.credential_vault import CredentialVault, VaultError


def validate_bridge_session(db, row, relay):
    """Match one fresh Windows bridge identity; never decrypt credentials or issue commands."""
    try:
        vault = CredentialVault()
    except VaultError as exc:
        raise AccountError("credential vault unavailable; cannot verify the saved account", 503) from exc
    for bridge_id in relay.accounts:
        session = relay.get(bridge_id)
        if session is None or relay.session_health(bridge_id) != "connected":
            continue
        snapshot = session.snapshot or {}
        identity = snapshot.get("account") or {}
        if (identity.get("connected") is not True or identity.get("trade_mode") != "demo"
                or identity.get("server") != row["server"]):
            continue
        fingerprint = vault.fingerprint(row["tenant_id"], row["provider"], row["server"], str(identity.get("login") or ""))
        if fingerprint != row["login_fingerprint"]:
            continue
        symbol = row["validation_symbol"]
        quote = (snapshot.get("quotes") or {}).get(symbol)
        if not isinstance(quote, dict):
            raise AccountError("ไม่พบ symbol ของบัญชีนี้ในข้อมูล MT5 · เลือกชื่อให้ตรงกับ Market Watch", 409)
        try:
            bid, ask, tick_time = (float(quote.get(key) or 0) for key in ("bid", "ask", "t"))
        except (ValueError, TypeError) as exc:
            raise AccountError("ข้อมูลราคาจาก MT5 ไม่ถูกต้อง", 409) from exc
        if not all(math.isfinite(v) and v > 0 for v in (bid, ask, tick_time)) or ask < bid:
            raise AccountError("ข้อมูลราคาจาก MT5 ไม่ถูกต้อง", 409)
        # A quote's broker timestamp may differ from UTC; validation proves the
        # account/session match, never certifies order execution or market freshness.
        age = time.time() - tick_time
        with db.cursor() as cur:
            cur.execute("UPDATE broker_accounts SET connection_status='ready_read_only', execution_enabled=0, updated_at=? "
                        "WHERE id=? AND tenant_id=? AND updated_at=? AND execution_enabled=0",
                        (time.time(), row["id"], row["tenant_id"], row["updated_at"]))
            if cur.rowcount != 1:
                raise AccountError("ข้อมูลบัญชีเปลี่ยนระหว่างตรวจสอบ กรุณา Refresh และลองใหม่", 409)
        return {"account_id": row["id"], "connection_status": "ready_read_only", "read_only": True,
                "execution_enabled": False, "terminal_selection": "automatic", "terminal_host": "windows_bridge",
                "server": row["server"], "symbol": symbol, "tick": {"bid": bid, "ask": ask, "time": tick_time},
                "quote_stale": not -5 <= age <= 30, "note": "Account identity matched via Windows bridge; no order sent"}
    raise AccountError("ยังไม่พบ MT5 Demo session ที่ตรงบัญชีนี้ · เปิดและล็อกอินบัญชีบน Windows PC ให้ bridge เชื่อมต่อก่อน", 409)


def validate_demo_account(db: Database, tenant_id: str, account_id: str,
                          user: dict[str, Any], *, relay=None) -> dict[str, Any]:
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
    if row["execution_enabled"]:
        raise AccountError("หยุด execution ก่อนตรวจสอบการเชื่อมต่อ", 409)
    if relay is not None:
        if not relay.enabled:
            raise AccountError("Windows MT5 bridge ยังไม่เปิดใช้งานบน VM100", 503)
        return validate_bridge_session(db, row, relay)
    raise AccountError("เชื่อมต่อ Windows MT5 bridge ก่อนตรวจสอบบัญชี", 503)
