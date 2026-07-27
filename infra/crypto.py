import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    secret = os.getenv("KEY_ENCRYPTION_SECRET")
    if not secret:
        raise RuntimeError("KEY_ENCRYPTION_SECRET not set. Add it to .env")
    return Fernet(secret.encode())


def encrypt_key(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_key(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()
