"""
encryption.py — Fernet-based encryption for storing OAuth tokens at rest.

Uses ENCRYPTION_KEY env var (a Fernet key). Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import os
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_key = os.environ.get("ENCRYPTION_KEY", "")
_fernet = Fernet(_key.encode()) if _key else None


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return the base64-encoded ciphertext."""
    if not _fernet:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to the original string."""
    if not _fernet:
        raise RuntimeError("ENCRYPTION_KEY is not set")
    return _fernet.decrypt(ciphertext.encode()).decode()
