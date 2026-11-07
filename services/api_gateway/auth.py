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
from services.api_gateway.roles import ADMIN, normalize_role

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
    """Create the demo account (admin by default) and heal roles from older builds."""
    sec = settings.security
    email = str(sec.get("demo_user", "demo@no7.ai")).lower().strip()
    password = sec.get("demo_password", "no7demo1234")
    role = normalize_role(sec.get("demo_role", ADMIN))
    row = db.query_one("SELECT email, role FROM users WHERE email = ?", (email,))
    if row is None:
        db.execute("INSERT INTO users(email, password_hash, role, created_at, active) "
                   "VALUES(?,?,?,?,1)",
                   (email, hash_password(password), role, time.time()))
    elif normalize_role(row["role"]) != str(row["role"]).lower():
        # e.g. the old "owner" role: keep the data, make it canonical
        db.execute("UPDATE users SET role = ? WHERE email = ?", (normalize_role(row["role"]), email))
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
    row = db.query_one(
        "SELECT email, password_hash, role, active FROM users WHERE email = ?",
        (email.lower().strip(),))
    if row is None:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    # A disabled account must not be able to log in, even with the right password.
    if not bool(row["active"] if row["active"] is not None else 1):
        db.audit(row["email"], "auth.disabled_login", {})
        return None
    role = normalize_role(row["role"])
    db.execute("UPDATE users SET last_login_at = ? WHERE email = ?", (time.time(), row["email"]))
    token, ttl = create_token(settings, row["email"], role)
    db.audit(row["email"], "auth.login", {"role": role})
    return {"token": token, "expires_in": ttl, "user": {"email": row["email"], "role": role},
            "jwt_secret_is_default": settings.security["jwt_secret"] == "no7-dev-only-secret"
            or os.environ.get("NO7_JWT_SECRET", "") in ("", "change-me-to-a-long-random-string")
            or len(settings.security["jwt_secret"]) < 32}

class LoginThrottle:
    """Slow down password guessing without needing a WAF.

    Failures are counted per (email, client IP) inside a rolling window; once the
    limit is hit the key is locked with exponential backoff. A successful login
    clears the counter. Unknown emails are throttled exactly like real ones, so
    the response cannot be used to enumerate accounts.
    """

    def __init__(self, db: Database, max_failures: int = 5, window_seconds: int = 900,
                 lock_seconds: int = 300, max_lock_seconds: int = 3600) -> None:
        self.db = db
        self.max_failures = max(1, int(max_failures))
        self.window_seconds = max(1, int(window_seconds))
        self.lock_seconds = max(1, int(lock_seconds))
        self.max_lock_seconds = max(self.lock_seconds, int(max_lock_seconds))

    def _row(self, key: str):
        return self.db.query_one(
            "SELECT failures, first_at, locked_until FROM login_throttle WHERE key = ?", (key,))

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Return (locked, retry_after_seconds)."""
        now = now if now is not None else time.time()
        row = self._row(key)
        if row is None:
            return False, 0
        locked_until = float(row["locked_until"] or 0)
        if locked_until > now:
            return True, max(1, int(round(locked_until - now)))
        return False, 0

    def register_failure(self, key: str, now: float | None = None) -> int:
        """Count one failure; return the lock length in seconds (0 = still allowed)."""
        now = now if now is not None else time.time()
        row = self._row(key)
        failures, first_at = (0, now) if row is None else (int(row["failures"] or 0), float(row["first_at"] or now))
        if now - first_at > self.window_seconds:
            failures, first_at = 0, now
        failures += 1
        lock = 0
        if failures >= self.max_failures:
            over = failures - self.max_failures
            lock = min(self.max_lock_seconds, self.lock_seconds * (2 ** min(over, 10)))
        self.db.execute(
            "INSERT OR REPLACE INTO login_throttle(key, failures, first_at, locked_until) VALUES(?,?,?,?)",
            (key, failures, first_at, now + lock if lock else 0.0),
        )
        return lock

    def reset(self, key: str) -> None:
        self.db.execute("DELETE FROM login_throttle WHERE key = ?", (key,))

    @staticmethod
    def key_for(email: str, client_ip: str) -> str:
        return f"{(email or '').lower().strip()}|{(client_ip or 'unknown').strip()}"
