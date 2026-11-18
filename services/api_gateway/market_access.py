"""Chart account routing without changing the execution broker or logging in."""
from fastapi import HTTPException

from services.api_gateway.accounts import list_broker_accounts
from services.api_gateway.credential_vault import CredentialVault, VaultError
from services.api_gateway.terminal_views import list_terminal_views


def market_accounts(runtime, user):
    accounts = list_broker_accounts(runtime.db, user.get("tenant_id", ""), user)
    try:
        vault = CredentialVault()
    except VaultError:
        vault = None
    for account in accounts:
        account["market_broker_id"] = None
        account["market_connected"] = False
        row = runtime.db.query_one(
            "SELECT login_fingerprint FROM broker_accounts WHERE id = ? AND tenant_id = ?",
            (account["id"], user.get("tenant_id", "")))
        if vault is None or row is None or account["provider"] != "mt5":
            continue
        for adapter in runtime.registry.all():
            if getattr(adapter, "adapter_type", "") != "bridge":
                continue
            session = runtime.bridge.get(adapter.account_id)
            if session is None or adapter.health().value != "connected":
                continue
            identity = (session.snapshot or {}).get("account") or {}
            if (identity.get("connected") is not True
                    or identity.get("trade_mode") != account["account_type"]
                    or identity.get("server") != account["server"]):
                continue
            fingerprint = vault.fingerprint(user["tenant_id"], "mt5", account["server"],
                                            str(identity.get("login") or ""))
            if fingerprint == row["login_fingerprint"]:
                account["market_broker_id"] = adapter.id
                account["market_connected"] = True
                break
    return accounts + list_terminal_views(runtime, user)


def chart_source(runtime, user, symbol, account_id=None):
    if not account_id:
        return runtime.market.chart_source(symbol)
    account = next((a for a in market_accounts(runtime, user) if a["id"] == account_id), None)
    if account is None:
        raise HTTPException(404, "broker account not found")
    if not account["market_connected"]:
        raise HTTPException(503, "บัญชีนี้ยังไม่มี MT5 session ที่ยืนยันตรงกัน; เลือกกราฟตลาดกลางเพื่อดูราคา")
    return runtime.registry.get(account["market_broker_id"]), "mt5-live"
