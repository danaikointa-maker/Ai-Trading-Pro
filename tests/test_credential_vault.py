import pytest

from services.api_gateway.credential_vault import CredentialVault, VaultError


def test_vault_encrypts_and_binds_credentials_to_account():
    vault = CredentialVault(CredentialVault.generate_key())
    ciphertext = vault.encrypt("account-a", "123456", "demo-password")

    assert b"123456" not in ciphertext
    assert b"demo-password" not in ciphertext
    assert vault.decrypt("account-a", ciphertext) == {
        "login": "123456", "password": "demo-password"
    }
    with pytest.raises(VaultError, match="invalid for this account"):
        vault.decrypt("account-b", ciphertext)


def test_vault_rejects_missing_or_invalid_master_key(monkeypatch):
    monkeypatch.delenv("NO7_CREDENTIAL_VAULT_KEY", raising=False)
    with pytest.raises(VaultError, match="not configured"):
        CredentialVault()
    with pytest.raises(VaultError, match="32-byte key"):
        CredentialVault("not-a-valid-key")