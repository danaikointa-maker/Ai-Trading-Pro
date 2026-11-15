"""One-time platform super-admin provisioning."""
from __future__ import annotations

import time

from packages.persistence.db import Database
from services.api_gateway.auth import hash_password
from services.api_gateway.roles import PLATFORM_SUPER_ADMIN, VIEWER
from services.api_gateway.users import UserError, _check_password, _norm_email


def create_platform_super_admin(db: Database, email: str, password: str) -> dict[str, str]:
    try:
        normalized_email = _norm_email(email)
        checked_password = _check_password(password)
    except UserError as exc:
        raise ValueError(str(exc)) from exc

    existing_platform_admin = db.query_one(
        "SELECT email FROM users WHERE platform_role = ? AND active = 1 LIMIT 1",
        (PLATFORM_SUPER_ADMIN,),
    )
    if existing_platform_admin:
        raise ValueError("a platform super-admin already exists; use the approved recovery procedure")
    if db.query_one("SELECT email FROM users WHERE email = ?", (normalized_email,)):
        raise ValueError("email is already in use; platform authority is never granted by promotion")

    db.execute(
        "INSERT INTO users(email, password_hash, role, created_at, active, tenant_id, platform_role) "
        "VALUES(?,?,?,?,1,NULL,?)",
        (normalized_email, hash_password(checked_password), VIEWER, time.time(), PLATFORM_SUPER_ADMIN),
    )
    return {"email": normalized_email, "platform_role": PLATFORM_SUPER_ADMIN}