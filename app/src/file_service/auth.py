"""Password verification and opaque server-side session helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_HASH_BYTES = 32


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


@dataclass(frozen=True)
class Principal:
    customer_id: str
    subject: str


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                             p=_SCRYPT_P, dklen=_HASH_BYTES, maxmem=64 * 1024 * 1024)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_encode(salt)}${_encode(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt_text, hash_text = encoded.split("$")
        if (algorithm != "scrypt" or int(n) != _SCRYPT_N or int(r) != _SCRYPT_R
                or int(p) != _SCRYPT_P):
            return False
        salt, expected = _decode(salt_text), _decode(hash_text)
        if len(salt) != _SALT_BYTES or len(expected) != _HASH_BYTES:
            return False
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
                                dklen=len(expected), maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def dummy_password_hash() -> str:
    return _DUMMY_PASSWORD_HASH


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
