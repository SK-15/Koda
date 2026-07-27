import pytest


class TestCrypto:
    def test_encrypt_decrypt_round_trip(self, monkeypatch):
        from cryptography.fernet import Fernet
        monkeypatch.setenv("KEY_ENCRYPTION_SECRET", Fernet.generate_key().decode())

        from infra.crypto import encrypt_key, decrypt_key
        encrypted = encrypt_key("sk-super-secret")
        assert encrypted != "sk-super-secret"
        assert decrypt_key(encrypted) == "sk-super-secret"

    def test_encrypt_missing_secret_raises(self, monkeypatch):
        monkeypatch.delenv("KEY_ENCRYPTION_SECRET", raising=False)

        from infra.crypto import encrypt_key
        with pytest.raises(RuntimeError):
            encrypt_key("sk-super-secret")
