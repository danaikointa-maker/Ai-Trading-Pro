"""Minimal but real authentication: PBKDF2 password hashes + JWT bearer tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Any

import jwt

from packages.persistence.db import Database
from packages.shared_schemas.settings import Settings

ITERATIONS = 210_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(expected, actual)
    except Exception:  # noqa: BLE001
        return False


def ensure_demo_user(db: Database, settings: Settings) -> str:
    sec = settings.security
    email = sec.get("demo_user", "demo@no7.ai")
    password = sec.get("demo_password", "no7demo1234")
    row = db.query_one("SELECT email FROM users WHERE email = ?", (email,))
    if row is None:
        db.execute("INSERT INTO users(email, password_hash, role, created_at) VALUES(?,?,?,?)",
                   (email, hash_password(password), "owner", time.time()))
    return email


def create_token(settings: Settings, email: str, role: str = "trader") -> tuple[str, int]:
    ttl = int(settings.security.get("jwt_ttl_minutes", 720)) * 60
    payload = {"sub": email, "role": role, "iat": int(time.time()), "exp": int(time.time()) + ttl,
               "iss": "no7-ai-trading-pro"}
    token = jwt.encode(payload, settings.security["jwt_secret"], algorithm="HS256")
    return token, ttl


def decode_token(settings: Settings, token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.security["jwt_secret"], algorithms=["HS256"],
                          issuer="no7-ai-trading-pro")
    except jwt.PyJWTError:
        return None


def authenticate(db: Database, settings: Settings, email: str, password: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT email, password_hash, role FROM users WHERE email = ?", (email.lower().strip(),))
    if row is None:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    token, ttl = create_token(settings, row["email"], row["role"])
    db.audit(row["email"], "auth.login", {"role": row["role"]})
    return {"token": token, "expires_in": ttl, "user": {"email": row["email"], "role": row["role"]},
            "jwt_secret_is_default": settings.security["jwt_secret"] == "no7-dev-only-secret"
            or os.environ.get("NO7_JWT_SECRET", "") in ("", "change-me-to-a-long-random-string")
            or len(settings.security["jwt_secret"]) < 32}
