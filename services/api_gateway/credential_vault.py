"""Authenticated encryption for broker credentials stored outside process env."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


KEY_ENV = "NO7_CREDENTIAL_VAULT_KEY"
KEY_VERSION = "1"


class VaultError(RuntimeError):
    """The credential vault is unavailable or the ciphertext failed authentication."""


class CredentialVault:
    def __init__(self, encoded_key: str | None = None) -> None:
        value = encoded_key if encoded_key is not None else os.environ.get(KEY_ENV, "")
        if not value:
            raise VaultError(f"{KEY_ENV} is not configured in the process environment")
        try:
            key = base64.urlsafe_b64decode(value.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise VaultError(f"{KEY_ENV} must be a URL-safe base64 encoded 32-byte key") from exc
        if len(key) != 32:
            raise VaultError(f"{KEY_ENV} must decode to exactly 32 bytes")
        self._key = key
        self._cipher = AESGCM(key)
        self._fingerprint_key = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=b"no7-vault-v1",
            info=b"broker-account-fingerprint",
        ).derive(key)

    @staticmethod
    def generate_key() -> str:
        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")

    def encrypt(self, account_id: str, login: str, password: str) -> bytes:
        if not account_id or not login or not password:
            raise VaultError("account ID, broker login and password are required")
        nonce = os.urandom(12)
        plaintext = json.dumps({"login": login, "password": password}, separators=(",", ":")).encode()
        return nonce + self._cipher.encrypt(nonce, plaintext, account_id.encode("utf-8"))

    def decrypt(self, account_id: str, ciphertext: bytes) -> dict[str, str]:
        try:
            raw = bytes(ciphertext)
            if len(raw) < 29:
                raise ValueError("ciphertext too short")
            plaintext = self._cipher.decrypt(raw[:12], raw[12:], account_id.encode("utf-8"))
            value = json.loads(plaintext)
            if not isinstance(value, dict) or not all(isinstance(value.get(key), str)
                                                       for key in ("login", "password")):
                raise ValueError("invalid credential payload")
            return {"login": value["login"], "password": value["password"]}
        except Exception as exc:  # noqa: BLE001 - never expose cryptographic details
            raise VaultError("credential ciphertext is invalid for this account or key") from exc

    def fingerprint(self, tenant_id: str, provider: str, server: str, login: str) -> str:
        value = "\0".join((tenant_id, provider.strip().lower(), server.strip().lower(), login.strip()))
        return hmac.new(self._fingerprint_key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_login(login: str) -> str:
    return "*" * max(4, len(login) - 4) + login[-4:]