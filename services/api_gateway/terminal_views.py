"""One-use operator proof for private, read-only MT5 position views."""
import hashlib
import hmac
import json
import math
import secrets
import time
from uuid import uuid4

from fastapi import HTTPException

from services.api_gateway.credential_vault import mask_login
from services.bridge.relay import BridgeError


def identity_hash(relay, account_id, identity):
    key = relay.accounts.get(account_id)
    if not key:
        return ""
    value = json.dumps([account_id, str(identity.get("login") or ""), identity.get("server"),
                        identity.get("trade_mode")], separators=(",", ":"))
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def issue_link_code(runtime, account_id, session_id, token):
    relay = runtime.bridge
    relay.require_enabled()
    relay.check_token(account_id, token)
    session = relay.get(account_id)
    if session is None or session.session_id != session_id or relay.session_health(account_id) != "connected":
        raise BridgeError("a fresh terminal session is required")
    identity = (session.snapshot or {}).get("account") or {}
    relay._check_identity(account_id, identity)
    if identity.get("trade_mode") != "demo" or identity.get("connected") is not True:
        raise BridgeError("read-only linking currently requires a connected Demo terminal")
    code = secrets.token_hex(16).upper()
    digest = hashlib.sha256(code.encode()).hexdigest()
    expires = time.time() + 600
    with runtime.db.cursor() as cur:
        cur.execute("DELETE FROM terminal_link_codes WHERE expires_at < ? OR bridge_account = ?",
                    (time.time(), account_id))
        cur.execute("INSERT INTO terminal_link_codes(code_hash,bridge_account,identity_hash,label,server,"
                    "account_type,masked_login,expires_at) VALUES(?,?,?,?,?,?,?,?)",
                    (digest, account_id, identity_hash(relay, account_id, identity), "MT5 Demo · read-only",
                     identity["server"], "demo", mask_login(str(identity["login"])), expires))
    runtime.db.audit("terminal-publisher", "terminal_view.code_issued", {"bridge_account": account_id})
    return {"code": code, "expires_at": expires, "read_only": True}


def claim_terminal(runtime, user, code):
    cleaned = str(code).strip().replace("-", "").upper()
    digest = hashlib.sha256(cleaned.encode()).hexdigest()
    tenant, owner = user["tenant_id"], user["email"]
    with runtime.db.cursor() as cur:
        row = cur.execute("SELECT * FROM terminal_link_codes WHERE code_hash=? AND consumed_at IS NULL "
                          "AND expires_at>?", (digest, time.time())).fetchone()
        if row is None:
            raise HTTPException(400, "รหัสผูก terminal ไม่ถูกต้อง หมดอายุ หรือถูกใช้ไปแล้ว")
        session = runtime.bridge.get(row["bridge_account"])
        if session is None or runtime.bridge.session_health(row["bridge_account"]) != "connected":
            raise HTTPException(409, "MT5 ยังไม่เชื่อมต่อ กรุณารอให้ terminal พร้อมแล้วลองใหม่")
        current = identity_hash(runtime.bridge, row["bridge_account"], (session.snapshot or {}).get("account") or {})
        if not hmac.compare_digest(current, row["identity_hash"]):
            raise HTTPException(409, "บัญชีใน terminal เปลี่ยนแล้ว ต้องออกรหัสผูกใหม่")
        existing = cur.execute("SELECT id FROM terminal_view_links WHERE tenant_id=? AND owner_email=? "
                               "AND bridge_account=? AND identity_hash=?",
                               (tenant, owner, row["bridge_account"], current)).fetchone()
        link_id = existing["id"] if existing else "terminal-" + uuid4().hex
        if existing is None:
            cur.execute("INSERT INTO terminal_view_links VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (link_id, tenant, owner, row["bridge_account"], current, row["label"], row["server"],
                         row["account_type"], row["masked_login"], time.time()))
        cur.execute("UPDATE terminal_link_codes SET consumed_at=? WHERE code_hash=? AND consumed_at IS NULL",
                    (time.time(), digest))
        if cur.rowcount != 1:
            raise HTTPException(409, "รหัสถูกใช้ไปแล้ว")
    runtime.db.audit(owner, "terminal_view.linked", {"id": link_id, "read_only": True})
    return {"id": link_id, "read_only": True, "execution_enabled": False}


def list_terminal_views(runtime, user):
    rows = runtime.db.query("SELECT * FROM terminal_view_links WHERE tenant_id=? AND owner_email=?",
                            (user.get("tenant_id", ""), user.get("email", "")))
    result = []
    for row in rows:
        session = runtime.bridge.get(row["bridge_account"])
        current = identity_hash(runtime.bridge, row["bridge_account"], (session.snapshot or {}).get("account") or {}) if session else ""
        connected = bool(current and hmac.compare_digest(current, row["identity_hash"])
                         and runtime.bridge.session_health(row["bridge_account"]) == "connected")
        adapter = next((a for a in runtime.registry.all() if getattr(a, "account_id", None) == row["bridge_account"]), None)
        result.append({"id": row["id"], "label": row["label"], "server": row["server"],
                       "account_type": row["account_type"], "login": row["masked_login"], "kind": "terminal_read_only",
                       "market_connected": connected and adapter is not None,
                       "market_broker_id": adapter.id if adapter else None,
                       "execution_enabled": False, "can_trade": False})
    return result


def private_positions(runtime, user, account_id, broker_id, symbol):
    empty = {"available": False, "positions": [], "read_only": True,
             "reason": "ผูก terminal แบบอ่านอย่างเดียวในหน้า Brokers ก่อน เพื่อแสดงไม้และ SL/TP จริง"}
    links = list_terminal_views(runtime, user)
    link = next((row for row in links if row["id"] == account_id and row["market_broker_id"] == broker_id), None)
    if link is None:
        return empty
    if not link["market_connected"]:
        return {**empty, "reason": "terminal หลุดหรือบัญชีเปลี่ยน · ยังยืนยันสถานะไม้ไม่ได้"}
    adapter = runtime.registry.get(broker_id)
    snapshot = runtime.bridge.snapshot(adapter.account_id)
    binding = runtime.db.query_one("SELECT identity_hash FROM terminal_view_links WHERE id=? AND tenant_id=? AND owner_email=?",
                                   (account_id, user.get("tenant_id", ""), user.get("email", "")))
    if binding is None or not hmac.compare_digest(binding["identity_hash"], identity_hash(
            runtime.bridge, adapter.account_id, snapshot.get("account") or {})):
        return {**empty, "reason": "บัญชี MT5 เปลี่ยนแล้ว ต้องผูก terminal ใหม่"}
    status = snapshot.get("positions_status") or {}
    try:
        age = time.time() - float(status.get("captured_at") or 0)
    except (TypeError, ValueError):
        return {**empty, "reason": "เวลาของข้อมูล position ไม่ถูกต้อง"}
    if snapshot.get("positions_scope") != "private" or status.get("available") is not True or not 0 <= age <= 5:
        return {**empty, "reason": "ยังไม่มีสถานะ position สดจาก MT5 · ต้องเปิด publisher --include-positions"}
    if not isinstance(snapshot.get("positions"), list):
        return {**empty, "reason": "ยังยืนยันรายการ position ไม่ได้"}
    positions = []
    for raw in snapshot["positions"]:
        if not isinstance(raw, dict):
            return {**empty, "reason": "ข้อมูล position ไม่ถูกต้อง"}
        if raw.get("symbol") != symbol:
            continue
        try:
            values = {key: float(raw.get(key) or 0) for key in ("entry", "sl", "tp", "volume")}
        except (TypeError, ValueError):
            return {**empty, "reason": "ข้อมูล position ไม่ถูกต้อง"}
        if not all(math.isfinite(value) and value >= 0 for value in values.values()):
            return {**empty, "reason": "ข้อมูล position ไม่ครบหรือไม่ถูกต้อง"}
        if values["entry"] <= 0 or values["volume"] <= 0 or not raw.get("ticket") or raw.get("direction") not in {"up", "down"}:
            return {**empty, "reason": "ข้อมูล position ไม่ครบหรือไม่ถูกต้อง"}
        positions.append({"ticket": str(raw.get("ticket") or ""), "symbol": symbol,
                          "direction": raw.get("direction"), **values})
    return {"available": True, "positions": positions, "read_only": True,
            "reason": "" if positions else "ไม่มีไม้เปิดของสัญลักษณ์นี้ในบัญชีที่ผูกไว้", "age_seconds": age}
