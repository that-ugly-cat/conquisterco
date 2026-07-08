"""Password hashing (stdlib, niente dipendenze) per l'auth di Fase 4.

PBKDF2-HMAC-SHA256 con salt per utente. Formato salvato in users.password_hash:
    <salt_hex>$<hash_hex>
"""

from __future__ import annotations

import hashlib
import hmac
import os

_ITER = 200_000


def hash_password(pw: str, *, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return f"{salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    salt_hex, h_hex = stored.split("$", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return hmac.compare_digest(h.hex(), h_hex)
